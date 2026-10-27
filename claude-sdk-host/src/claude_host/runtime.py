"""Claude Agent SDK host runtime runner.

Owns the execution lifecycle for Claude Agent SDK sessions:
- Allowlisted child process environment with forbidden credential clearing
- Strict SDK options, exact declared MCP tools, and built-in denylist
- PreToolUse hook enforcing tool allowlist and local tool activity
- Message stream processing, token deduplication and reconciliation
- Monotonic deadline, observed token ceiling and honest accounting completeness
- Bounded cancellation with interrupt, stream close and resource cleanup
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .contracts import RunFailure, RunSpec, RuntimeEvent
from .usage import UsageMeter

logger = logging.getLogger(__name__)

DISALLOWED_BUILTIN_TOOLS: tuple[str, ...] = (
    "Bash",
    "BashOutput",
    "KillShell",
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Task",
    "Agent",
    "TodoWrite",
    "ExitPlanMode",
    "SlashCommand",
    "Skill",
)

ALLOWLISTED_ENV_KEYS: frozenset[str] = frozenset(
    {
        # System / Runtime / Locale
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        # Proxy configuration
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "NO_PROXY",
        "no_proxy",
        "ALL_PROXY",
        "all_proxy",
        # Official CLI auth and state directory configuration
        "CLAUDE_CONFIG_DIR",
        "CLAUDE_STATE_DIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_RUNTIME_DIR",
    }
)

FORBIDDEN_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "CLAUDE_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_PROVIDER",
        "API_KEY",
        "CLAUDE_BASE_URL",
        "OAUTH_TOKEN",
        "CLAUDE_OAUTH_TOKEN",
        "ANTHROPIC_OAUTH_TOKEN",
    }
)

SAFE_STOP_REASONS: frozenset[str] = frozenset(
    {
        "end_turn",
        "max_turns",
        "stop_sequence",
        "tool_use",
        "cancelled",
        "deadline_exceeded",
        "budget_exceeded",
        "provider_error",
        "rate_limited",
        "provider_stream_incomplete",
        "credential_grant_inactive",
        "missing_author_submission",
    }
)


def _map_stop_reason(val: Any, is_error: bool = False, api_status: int | None = None) -> str:
    """Map raw provider subtype/stop reason to a finite safe code set."""
    if api_status in (401, 403) or val == "authentication_failed":
        return "reauthentication_required"
    if api_status == 429:
        return "rate_limited"
    s = str(val or "").strip().lower()
    if s in ("end_turn", "success"):
        return "end_turn"
    if s in ("stop_sequence",):
        return "stop_sequence"
    if s in ("tool_use",):
        return "tool_use"
    if s in ("max_turns", "error_max_turns"):
        return "max_turns"
    if s in ("rate_limit", "rate_limited"):
        return "rate_limited"
    if s in ("cancelled",):
        return "cancelled"
    if s in ("deadline_exceeded", "timed_out"):
        return "deadline_exceeded"
    if s in ("budget_exceeded",):
        return "budget_exceeded"
    if s in ("credential_grant_inactive",):
        return "credential_grant_inactive"
    if s in ("missing_author_submission",):
        return "missing_author_submission"
    if s in ("provider_stream_incomplete",):
        return "provider_stream_incomplete"
    # Never forward arbitrary provider strings
    return "provider_error" if is_error else "end_turn"


def _extract_text_from_block(block: Any) -> str | None:
    """Extract plain text from an SDK TextBlock or dict block."""
    if isinstance(block, dict):
        if block.get("type") == "text":
            return block.get("text")
        return None
    cls_name = type(block).__name__
    if cls_name in (
        "ThinkingBlock",
        "ToolUseBlock",
        "ToolResultBlock",
        "ServerToolUseBlock",
        "ServerToolResultBlock",
    ):
        return None
    b_type = getattr(block, "type", None)
    if b_type in ("thinking", "tool_use", "tool_result"):
        return None
    if hasattr(block, "text") and isinstance(block.text, str):
        return block.text
    return None


def _has_tool_use_in_message(message: Any) -> bool:
    """Check if message content contains tool use blocks."""
    content = _get(message, "content", []) or []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") in ("tool_use", "server_tool_use"):
                return True
        else:
            cls_name = type(block).__name__
            if cls_name in ("ToolUseBlock", "ServerToolUseBlock"):
                return True
            if getattr(block, "type", None) in ("tool_use", "server_tool_use"):
                return True
    return False


def _load_sdk() -> Any:
    import claude_agent_sdk

    return claude_agent_sdk


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class _SessionState:
    """Internal runtime state for an active session query."""

    def __init__(self, session_id: str, deadline_monotonic: float) -> None:
        self.session_id = session_id
        self.deadline_monotonic = deadline_monotonic
        self.cancelled = False
        self.cancel_event = asyncio.Event()
        self.stream: Any = None


class SDKRunner:
    """Executor for Claude Agent SDK queries and agent sessions."""

    def __init__(
        self,
        environment: dict[str, str] | None = None,
        sdk: object | None = None,
    ) -> None:
        self._operator_env = environment
        self._sdk = sdk
        self._sessions: dict[str, _SessionState] = {}

    def _build_subprocess_env(self) -> dict[str, str]:
        """Construct allowlisted child environment and blank out credentials.

        Child SDK merges supplied env with os.environ: blank every inherited
        key in os.environ that is not in ALLOWLISTED_ENV_KEYS. Ensure no
        OAuth/API/provider overrides survive. Keep operator auth path and
        fixed proxy values. Never mutates global os.environ.
        """
        env: dict[str, str] = {}

        # 1. Blank every inherited key in os.environ that is not in the allowlist
        for key in os.environ:
            if key not in ALLOWLISTED_ENV_KEYS:
                env[key] = ""

        # 2. Select allowlisted keys from operator environment (or os.environ)
        source = self._operator_env if self._operator_env is not None else os.environ
        for key in ALLOWLISTED_ENV_KEYS:
            if key in source:
                env[key] = str(source[key])

        # 3. Explicitly reject/clear API key / provider / OAuth / base url fallbacks
        for key in FORBIDDEN_ENV_KEYS:
            env[key] = ""

        # 4. Mandatory telemetry and traffic disabling
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["CLAUDE_DO_NOT_TRACK"] = "1"
        env["DISABLE_TELEMETRY"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"

        return env

    def cancel(self, session_id: str) -> Any:
        """Interrupt and cancel a running session query.

        Interrupts the active stream/client and sets the cancellation signal.
        Does not call stream.aclose() while __anext__ is running.
        Returns an awaitable Task for bounded interrupt execution.
        """
        session = self._sessions.get(session_id)
        if session is None:

            async def _noop() -> None:
                pass

            return asyncio.create_task(_noop())

        session.cancelled = True
        session.cancel_event.set()

        async def _interrupt() -> None:
            stream = session.stream
            if stream is not None and hasattr(stream, "interrupt"):
                try:
                    res = stream.interrupt()
                    if inspect.isawaitable(res):
                        await asyncio.wait_for(res, timeout=5.0)
                except Exception as err:
                    logger.warning("Interrupt error on session %s: %s", session_id, type(err).__name__)

        return asyncio.create_task(_interrupt())

    async def run(self, spec: RunSpec) -> AsyncIterator[RuntimeEvent]:
        """Run an SDK query or agent session yielding structured RuntimeEvents."""
        # 1. Verification before run initialization
        now = time.monotonic()
        remaining = spec.deadline_monotonic - now
        if remaining <= 0:
            raise RunFailure("deadline_exceeded", status_code=504)

        if spec.token_budget_remaining <= 0:
            raise RunFailure("budget_exhausted", status_code=400)

        if spec.session_id in self._sessions:
            raise RunFailure("session_already_active", status_code=409)

        sdk = self._sdk
        if sdk is None:
            try:
                sdk = _load_sdk()
            except ImportError as err:
                logger.error("Claude Agent SDK is not installed")
                raise RunFailure("sdk_unavailable", status_code=503) from err

        # 2. Local tools startup within remaining deadline
        if spec.local_tools is not None:
            rem = spec.deadline_monotonic - time.monotonic()
            if rem <= 0:
                raise RunFailure("deadline_exceeded", status_code=504)
            try:
                await asyncio.wait_for(spec.local_tools.start(), timeout=rem)
            except TimeoutError as err:
                logger.error("Local tools startup timed out for session %s", spec.session_id)
                if hasattr(spec.local_tools, "aclose"):
                    try:
                        await asyncio.wait_for(spec.local_tools.aclose(), timeout=5.0)
                    except Exception:
                        pass
                raise RunFailure("deadline_exceeded", status_code=504) from err
            except Exception as err:
                logger.error("Failed to start local tools for session %s: %s", spec.session_id, type(err).__name__)
                if hasattr(spec.local_tools, "aclose"):
                    try:
                        await asyncio.wait_for(spec.local_tools.aclose(), timeout=5.0)
                    except Exception:
                        pass
                raise RunFailure("local_tools_start_failed", status_code=503) from err

        # 3. Workdir setup within remaining deadline
        rem = spec.deadline_monotonic - time.monotonic()
        if rem <= 0:
            if spec.local_tools is not None and hasattr(spec.local_tools, "aclose"):
                try:
                    await asyncio.wait_for(spec.local_tools.aclose(), timeout=5.0)
                except Exception:
                    pass
            raise RunFailure("deadline_exceeded", status_code=504)

        workdir: Path
        owns_workdir = False
        if spec.workdir is not None:
            workdir = spec.workdir
            workdir.mkdir(parents=True, exist_ok=True)
        else:
            temp_dir = tempfile.mkdtemp(prefix=f"claude-host-run-{spec.session_id}-")
            workdir = Path(temp_dir)
            owns_workdir = True

        session_state = _SessionState(spec.session_id, spec.deadline_monotonic)
        self._sessions[spec.session_id] = session_state

        stream: Any = None
        meter = UsageMeter(model=spec.model)
        state = "completed"
        stop_reason = "end_turn"
        accounting_complete = False
        submission_emitted = False
        seen_text_messages: set[str] = set()
        current_provider_msg_id: str | None = None
        assistant_failure = None
        has_text_content = False
        pending_tool_use = False
        result_seen = False
        started_emitted = False
        next_task = None
        cancel_task = None
        last_lease_check = time.monotonic()

        try:
            # Merge MCP servers and declared tool names from local tools
            local_mcp: dict[str, Any] = {}
            local_tool_names: list[str] = []
            if spec.local_tools is not None:
                if hasattr(spec.local_tools, "sdk_servers"):
                    local_mcp = spec.local_tools.sdk_servers(sdk) or {}
                if hasattr(spec.local_tools, "allowed_tool_names"):
                    local_tool_names = spec.local_tools.allowed_tool_names() or []

            merged_mcp = {**spec.mcp_servers, **local_mcp}
            merged_allowed_tools = list(dict.fromkeys(list(spec.allowed_tools or []) + list(local_tool_names or [])))
            allowed_tool_set = frozenset(merged_allowed_tools)

            # PreToolUse hook enforcing tool allowlist and local_tools.check_active
            async def pre_tool_use_hook(
                input_data: Any,
                tool_use_id: str | None = None,
                context: Any = None,
            ) -> dict[str, Any]:
                tool_name = (
                    input_data.get("tool_name")
                    if isinstance(input_data, dict)
                    else getattr(input_data, "tool_name", "")
                )
                if tool_name not in allowed_tool_set:
                    reason = f"Tool '{tool_name}' is not allowed"
                    return {
                        "decision": "block",
                        "reason": reason,
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": reason,
                        },
                    }
                if spec.local_tools is not None and hasattr(spec.local_tools, "check_active"):
                    try:
                        active = await asyncio.wait_for(spec.local_tools.check_active(), timeout=5.0)
                        if not active:
                            reason = "credential_grant_inactive"
                            return {
                                "decision": "block",
                                "reason": reason,
                                "hookSpecificOutput": {
                                    "hookEventName": "PreToolUse",
                                    "permissionDecision": "deny",
                                    "permissionDecisionReason": reason,
                                },
                            }
                    except Exception:
                        reason = "credential_grant_inactive"
                        return {
                            "decision": "block",
                            "reason": reason,
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "permissionDecisionReason": reason,
                            },
                        }
                return {}

            max_turns = 1 if spec.profile == "completion" else spec.max_turns

            options_kwargs: dict[str, Any] = {
                "tools": [],
                "strict_mcp_config": True,
                "setting_sources": [],
                "permission_mode": "dontAsk",
                "verbatim_prompts": True,
                "include_partial_messages": True,
                "disallowed_tools": [*DISALLOWED_BUILTIN_TOOLS, "mcp__tms-execution__attach_evidence"],
                "allowed_tools": merged_allowed_tools,
                "mcp_servers": merged_mcp,
                "max_turns": max_turns,
                "cwd": str(workdir),
                "env": self._build_subprocess_env(),
                "extra_args": {"no-session-persistence": None},
                "model": spec.model,
                "system_prompt": spec.system_prompt,
            }

            if hasattr(spec, "agents") and spec.agents:
                options_kwargs["agents"] = spec.agents

            # No capability fallbacks in production: construct real HookMatcher and ClaudeAgentOptions
            try:
                if not hasattr(sdk, "ClaudeAgentOptions") or not hasattr(sdk, "HookMatcher"):
                    raise RunFailure("sdk_unavailable", status_code=503)

                hooks = {"PreToolUse": [sdk.HookMatcher(hooks=[pre_tool_use_hook])]}
                options_kwargs["hooks"] = hooks
                options = sdk.ClaudeAgentOptions(**options_kwargs)
                stream = sdk.query(prompt=spec.prompt, options=options)
                session_state.stream = stream
            except RunFailure:
                raise
            except Exception as err:
                logger.error(
                    "SDK options/query initialization failed for session %s: %s",
                    spec.session_id,
                    type(err).__name__,
                )
                raise RunFailure("sdk_initialization_failed", status_code=503) from err

            # query() is lazy; startup is emitted only after its first successful iteration.

            # Message processing loop
            while True:
                # Poll independently of event arrival: a continuously streaming provider
                # must not postpone revocation checks indefinitely.
                if spec.local_tools is not None and time.monotonic() - last_lease_check >= 5:
                    try:
                        active = await asyncio.wait_for(spec.local_tools.check_active(), timeout=5)
                        if active is not True:
                            raise RunFailure("credential_grant_inactive")
                    except Exception:
                        state, stop_reason = "failed", "credential_grant_inactive"
                        break
                    last_lease_check = time.monotonic()
                remaining_time = spec.deadline_monotonic - time.monotonic()
                if remaining_time <= 0:
                    state = "timed_out"
                    stop_reason = "deadline_exceeded"
                    break

                if session_state.cancelled or session_state.cancel_event.is_set():
                    state = "cancelled"
                    stop_reason = "cancelled"
                    break

                if spec.token_budget_remaining > 0 and meter.total_budget_tokens >= spec.token_budget_remaining:
                    state = "budget_exceeded"
                    stop_reason = "budget_exceeded"
                    break

                if not submission_emitted and spec.local_tools is not None:
                    src = getattr(spec.local_tools, "accepted_source", None)
                    if src:
                        submission_emitted = True
                        yield RuntimeEvent(kind="submission", data={"source": str(src)})

                next_task = asyncio.create_task(stream.__anext__())
                cancel_task = asyncio.create_task(session_state.cancel_event.wait())

                # Wait for next message while continuously guarding active lease every <= 5s
                while not next_task.done():
                    now = time.monotonic()
                    rem = spec.deadline_monotonic - now
                    if rem <= 0:
                        state = "timed_out"
                        stop_reason = "deadline_exceeded"
                        break

                    if session_state.cancelled or session_state.cancel_event.is_set():
                        state = "cancelled"
                        stop_reason = "cancelled"
                        break

                    time_to_lease = max(0.05, 5.0 - (now - last_lease_check))
                    timeout = min(rem, time_to_lease)

                    done, _ = await asyncio.wait(
                        [next_task, cancel_task],
                        timeout=timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if cancel_task in done or session_state.cancelled or session_state.cancel_event.is_set():
                        state = "cancelled"
                        stop_reason = "cancelled"
                        break

                    if next_task in done:
                        break

                    if time.monotonic() >= spec.deadline_monotonic:
                        state = "timed_out"
                        stop_reason = "deadline_exceeded"
                        break

                    if spec.local_tools is not None and hasattr(spec.local_tools, "check_active"):
                        if time.monotonic() - last_lease_check >= 5.0:
                            try:
                                active = await asyncio.wait_for(spec.local_tools.check_active(), timeout=5.0)
                                if not active:
                                    state = "failed"
                                    stop_reason = "credential_grant_inactive"
                                    break
                            except Exception:
                                state = "failed"
                                stop_reason = "credential_grant_inactive"
                                break
                            last_lease_check = time.monotonic()

                # If broken due to timeout, cancellation, or grant inactivity:
                if state in ("timed_out", "cancelled", "failed"):
                    if not next_task.done():
                        next_task.cancel()
                    cancel_task.cancel()
                    await asyncio.gather(next_task, cancel_task, return_exceptions=True)
                    break

                cancel_task.cancel()
                try:
                    await cancel_task
                except asyncio.CancelledError:
                    pass

                try:
                    message = next_task.result()
                except StopAsyncIteration:
                    break
                except Exception as err:
                    logger.error("SDK query stream ended with error: %s", type(err).__name__)
                    state = "failed"
                    stop_reason = "provider_error"
                    break

                if not started_emitted:
                    started_emitted = True
                    yield RuntimeEvent(kind="started", data={"model": spec.model})

                msg_type = type(message).__name__
                is_stream_event = (
                    msg_type == "StreamEvent"
                    or hasattr(message, "event")
                    or (isinstance(message, dict) and "event" in message)
                )
                is_assistant_message = (
                    msg_type == "AssistantMessage"
                    or (hasattr(message, "content") and hasattr(message, "usage"))
                    or (isinstance(message, dict) and "content" in message)
                )
                is_rate_limit_event = (
                    msg_type == "RateLimitEvent"
                    or hasattr(message, "rate_limit_info")
                    or (isinstance(message, dict) and "rate_limit_info" in message)
                )
                is_result_message = (
                    msg_type == "ResultMessage"
                    or (hasattr(message, "subtype") and hasattr(message, "duration_ms"))
                    or (
                        isinstance(message, dict)
                        and "subtype" in message
                        and ("duration_ms" in message or "is_error" in message)
                    )
                )

                # 1. StreamEvent
                if is_stream_event:
                    event = _get(message, "event", {})
                    if isinstance(event, dict):
                        e_type = event.get("type")
                        if e_type == "message_start":
                            msg = event.get("message", {})
                            if isinstance(msg, dict) and msg.get("id"):
                                current_provider_msg_id = str(msg.get("id"))
                        elif e_type == "content_block_delta":
                            delta = event.get("delta", {})
                            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                                text = delta.get("text")
                                if text:
                                    has_text_content = True
                                    if current_provider_msg_id:
                                        seen_text_messages.add(current_provider_msg_id)
                                    yield RuntimeEvent(kind="text_delta", data={"text": text})

                    for usage_delta in meter.observe(message):
                        yield RuntimeEvent(kind="usage", data=usage_delta)
                        if spec.token_budget_remaining > 0 and meter.total_budget_tokens >= spec.token_budget_remaining:
                            state = "budget_exceeded"
                            stop_reason = "budget_exceeded"
                            break
                    if state == "budget_exceeded":
                        break

                # 2. AssistantMessage
                elif is_assistant_message:
                    err = _get(message, "error")
                    if err:
                        state = "failed"
                        stop_reason = "provider_error"

                    # Provider message ID is in message_id (StreamEvent/AssistantMessage uuid is a distinct event UUID)
                    msg_id = _get(message, "message_id") or current_provider_msg_id
                    if not msg_id or msg_id not in seen_text_messages:
                        content = [] if err else (_get(message, "content", []) or [])
                        for block in content:
                            text = _extract_text_from_block(block)
                            if text:
                                has_text_content = True
                                yield RuntimeEvent(kind="text_delta", data={"text": text})
                        if msg_id:
                            seen_text_messages.add(msg_id)

                    if _has_tool_use_in_message(message):
                        pending_tool_use = True
                    else:
                        pending_tool_use = False

                    for usage_delta in meter.observe(message):
                        yield RuntimeEvent(kind="usage", data=usage_delta)
                        if spec.token_budget_remaining > 0 and meter.total_budget_tokens >= spec.token_budget_remaining:
                            state = "budget_exceeded"
                            stop_reason = "budget_exceeded"
                            break
                    if state == "budget_exceeded":
                        break

                # 3. RateLimitEvent
                elif is_rate_limit_event:
                    info = _get(message, "rate_limit_info")
                    status_val = str(_get(info, "status", "unknown"))
                    resets_at_val = _get(info, "resets_at")
                    yield RuntimeEvent(
                        kind="rate_limit",
                        data={"status": status_val, "resets_at": resets_at_val},
                    )
                    if status_val == "rejected":
                        state, stop_reason = "failed", "rate_limited"
                        break

                # 4. ResultMessage
                elif is_result_message:
                    result_seen = True
                    for usage_delta in meter.observe(message):
                        yield RuntimeEvent(kind="usage", data=usage_delta)

                    # Recheck final observed budget after ResultMessage, not only partial messages
                    if spec.token_budget_remaining > 0 and meter.total_budget_tokens >= spec.token_budget_remaining:
                        state = "budget_exceeded"
                        stop_reason = "budget_exceeded"
                        break

                    is_error = bool(_get(message, "is_error", False))
                    subtype = _get(message, "subtype", "")
                    api_status = _get(message, "api_error_status")

                    if assistant_failure:
                        state, stop_reason = "failed", assistant_failure
                    elif subtype in ("error_max_turns", "max_turns"):
                        if spec.profile != "completion":
                            state = "failed"
                            stop_reason = "max_turns"
                        else:
                            if has_text_content and not pending_tool_use:
                                state = "completed"
                                stop_reason = "max_turns"
                            else:
                                state = "failed"
                                stop_reason = "max_turns"
                    elif spec.profile == "completion" and pending_tool_use:
                        state, stop_reason = "failed", "unexpected_tool_use"
                    elif is_error:
                        state = "failed"
                        stop_reason = _map_stop_reason(subtype, is_error=True, api_status=api_status)
                    else:
                        state = "completed"
                        raw_stop = _get(message, "stop_reason") or subtype
                        stop_reason = _map_stop_reason(raw_stop, is_error=False)

                    break

            # Final check for accepted_source before terminal
            if not submission_emitted and spec.local_tools is not None:
                src = getattr(spec.local_tools, "accepted_source", None)
                if src:
                    submission_emitted = True
                    yield RuntimeEvent(kind="submission", data={"source": str(src)})

            if assistant_failure:
                state, stop_reason = "failed", assistant_failure

            # Stream ending without ResultMessage must fail with provider_stream_incomplete
            if not result_seen and state not in ("timed_out", "cancelled", "budget_exceeded", "failed"):
                state = "failed"
                stop_reason = "provider_stream_incomplete"

            # Authoring requires accepted_source before success
            if "author" in spec.profile.lower() and state == "completed":
                if not submission_emitted:
                    state = "failed"
                    stop_reason = "missing_author_submission"

            accounting_complete = state == "completed" and meter.is_accounting_complete()

            yield RuntimeEvent(
                kind="terminal",
                data={
                    "state": state,
                    "stop_reason": stop_reason,
                    "accounting_complete": accounting_complete,
                },
            )

        except asyncio.CancelledError:
            state = "cancelled"
            stop_reason = "cancelled"
            accounting_complete = False
            yield RuntimeEvent(
                kind="terminal",
                data={
                    "state": state,
                    "stop_reason": stop_reason,
                    "accounting_complete": accounting_complete,
                },
            )
            raise

        finally:
            pending_tasks = [task for task in (next_task, cancel_task) if task is not None]
            for pending in pending_tasks:
                if not pending.done():
                    pending.cancel()
            if pending_tasks:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.gather(*pending_tasks, return_exceptions=True), 1)
            if stream is not None:
                if hasattr(stream, "interrupt") and (session_state.cancelled or state != "completed"):
                    try:
                        res = stream.interrupt()
                        if inspect.isawaitable(res):
                            await asyncio.wait_for(res, timeout=5.0)
                    except Exception:
                        pass
                if hasattr(stream, "aclose"):
                    try:
                        await asyncio.wait_for(stream.aclose(), timeout=5.0)
                    except Exception:
                        pass

            if spec.local_tools is not None and hasattr(spec.local_tools, "aclose"):
                try:
                    await asyncio.wait_for(spec.local_tools.aclose(), timeout=5.0)
                except Exception as err:
                    logger.warning("local_tools aclose error: %s", type(err).__name__)

            if owns_workdir:
                shutil.rmtree(workdir, ignore_errors=True)

            self._sessions.pop(spec.session_id, None)
