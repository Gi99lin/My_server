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

ALLOWLISTED_ENV_KEYS: frozenset[str] = frozenset({
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
})

FORBIDDEN_ENV_KEYS: frozenset[str] = frozenset({
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_PROVIDER",
    "API_KEY",
})

SENSITIVE_ENV_MARKERS: tuple[str, ...] = (
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "TOKEN",
    "KEY",
    "CREDENTIAL",
    "ENCRYPTION",
)


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

        Never mutates global os.environ.
        """
        env: dict[str, str] = {}

        # 1. Blank out any secret-looking variable from parent process environment
        for key in os.environ:
            if key in FORBIDDEN_ENV_KEYS or any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS):
                env[key] = ""

        # 2. Select only allowlisted keys from operator environment (or os.environ)
        source = self._operator_env if self._operator_env is not None else os.environ
        for key, val in source.items():
            if key in ALLOWLISTED_ENV_KEYS:
                env[key] = str(val)

        # 3. Explicitly reject/clear API key / provider / base url fallbacks
        for key in FORBIDDEN_ENV_KEYS:
            env[key] = ""

        # 4. Mandatory telemetry and traffic disabling
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["CLAUDE_DO_NOT_TRACK"] = "1"
        env["DISABLE_TELEMETRY"] = "1"

        return env

    def cancel(self, session_id: str) -> Any:
        """Interrupt and cancel a running session query.

        Interrupts the active stream/client, closes the stream, and signals cancellation.
        Returns an awaitable Task so callers can optionally await completion.
        """
        session = self._sessions.get(session_id)
        if session is None:
            async def _noop() -> None:
                pass

            return asyncio.create_task(_noop())

        session.cancelled = True
        session.cancel_event.set()

        async def _interrupt_and_close() -> None:
            stream = session.stream
            if stream is not None:
                if hasattr(stream, "interrupt"):
                    try:
                        res = stream.interrupt()
                        if inspect.isawaitable(res):
                            await res
                    except Exception as err:
                        logger.warning("Interrupt error on session %s: %s", session_id, type(err).__name__)
                if hasattr(stream, "aclose"):
                    try:
                        await stream.aclose()
                    except Exception as err:
                        logger.warning("Stream aclose error on session %s: %s", session_id, type(err).__name__)

        return asyncio.create_task(_interrupt_and_close())

    async def run(self, spec: RunSpec) -> AsyncIterator[RuntimeEvent]:
        """Run an SDK query or agent session yielding structured RuntimeEvents."""
        # 1. Verification before run initialization
        now = time.monotonic()
        if spec.deadline_monotonic <= now:
            raise RunFailure("deadline_exceeded", status_code=504)

        if spec.session_id in self._sessions:
            raise RunFailure("session_already_active", status_code=409)

        sdk = self._sdk
        if sdk is None:
            try:
                sdk = _load_sdk()
            except ImportError as err:
                logger.error("Claude Agent SDK is not installed")
                raise RunFailure("sdk_unavailable", status_code=503) from err

        if spec.local_tools is not None:
            try:
                await spec.local_tools.start()
            except Exception as err:
                logger.error("Failed to start local tools for session %s: %s", spec.session_id, type(err).__name__)
                raise RunFailure("local_tools_start_failed", status_code=503) from err

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

        try:
            # Yield started event once run is initialized
            yield RuntimeEvent(kind="started", data={"model": spec.model})

            # Merge MCP servers and declared tool names from local tools
            local_mcp: dict[str, Any] = {}
            local_tool_names: list[str] = []
            if spec.local_tools is not None:
                if hasattr(spec.local_tools, "sdk_servers"):
                    local_mcp = spec.local_tools.sdk_servers(sdk) or {}
                if hasattr(spec.local_tools, "allowed_tool_names"):
                    local_tool_names = spec.local_tools.allowed_tool_names() or []

            merged_mcp = {**spec.mcp_servers, **local_mcp}
            merged_allowed_tools = list(
                dict.fromkeys(list(spec.allowed_tools or []) + list(local_tool_names or []))
            )
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
                        active = await spec.local_tools.check_active()
                        if not active:
                            reason = "Local tools session is inactive"
                            return {
                                "decision": "block",
                                "reason": reason,
                                "hookSpecificOutput": {
                                    "hookEventName": "PreToolUse",
                                    "permissionDecision": "deny",
                                    "permissionDecisionReason": reason,
                                },
                            }
                    except Exception as exc:
                        reason = f"Local tools check_active failed: {type(exc).__name__}"
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

            hooks: dict[str, list[Any]] = {}
            if hasattr(sdk, "HookMatcher"):
                hooks = {"PreToolUse": [sdk.HookMatcher(hooks=[pre_tool_use_hook])]}
            else:
                hooks = {"PreToolUse": [{"hooks": [pre_tool_use_hook]}]}

            max_turns = 1 if spec.profile == "completion" else spec.max_turns

            options_kwargs: dict[str, Any] = {
                "tools": [],
                "strict_mcp_config": True,
                "setting_sources": [],
                "permission_mode": "dontAsk",
                "verbatim_prompts": True,
                "include_partial_messages": True,
                "disallowed_tools": list(DISALLOWED_BUILTIN_TOOLS),
                "allowed_tools": merged_allowed_tools,
                "mcp_servers": merged_mcp,
                "hooks": hooks,
                "max_turns": max_turns,
                "cwd": str(workdir),
                "env": self._build_subprocess_env(),
                "extra_args": {"no-session-persistence": None},
                "model": spec.model,
                "system_prompt": spec.system_prompt,
            }

            if hasattr(spec, "agents") and getattr(spec, "agents"):
                options_kwargs["agents"] = getattr(spec, "agents")

            if hasattr(sdk, "ClaudeAgentOptions"):
                options = sdk.ClaudeAgentOptions(**options_kwargs)
            else:
                # Custom deterministic SDK object in probes
                options = options_kwargs

            stream = sdk.query(prompt=spec.prompt, options=options)
            session_state.stream = stream

            # Message processing loop
            while True:
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

                done, pending = await asyncio.wait(
                    [next_task, cancel_task],
                    timeout=remaining_time,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

                if not done:
                    state = "timed_out"
                    stop_reason = "deadline_exceeded"
                    break

                if cancel_task in done and session_state.cancel_event.is_set():
                    state = "cancelled"
                    stop_reason = "cancelled"
                    break

                try:
                    message = next_task.result()
                except StopAsyncIteration:
                    break
                except Exception as err:
                    logger.error("SDK query stream ended with error: %s", type(err).__name__)
                    state = "failed"
                    stop_reason = "provider_error"
                    break

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
                    or (isinstance(message, dict) and "subtype" in message and ("duration_ms" in message or "is_error" in message))
                )

                # 1. StreamEvent
                if is_stream_event:
                    event = _get(message, "event", {})
                    if isinstance(event, dict):
                        # Text delta extraction
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                                text = delta.get("text")
                                if text:
                                    msg_id = _get(message, "uuid") or "stream"
                                    seen_text_messages.add(msg_id)
                                    yield RuntimeEvent(kind="text_delta", data={"text": text})

                    # Usage observation from StreamEvent
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

                    msg_id = _get(message, "message_id") or _get(message, "uuid") or "assistant"
                    # If text was not already streamed via text deltas, emit text blocks now
                    if msg_id not in seen_text_messages:
                        content = _get(message, "content", []) or []
                        for block in content:
                            b_type = _get(block, "type", "")
                            # Text only: never forward thinking, raw tool payloads, headers or exceptions
                            if b_type not in ("thinking", "tool_use", "tool_result"):
                                text = _get(block, "text")
                                if text:
                                    yield RuntimeEvent(kind="text_delta", data={"text": text})

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

                # 4. ResultMessage
                elif is_result_message:
                    for usage_delta in meter.observe(message):
                        yield RuntimeEvent(kind="usage", data=usage_delta)

                    is_error = bool(_get(message, "is_error", False))
                    subtype = _get(message, "subtype", "")

                    if is_error:
                        if subtype in ("error_max_turns", "max_turns"):
                            state = "completed"
                            stop_reason = "max_turns"
                        else:
                            state = "failed"
                            api_status = _get(message, "api_error_status")
                            if api_status == 429:
                                stop_reason = "rate_limited"
                            elif api_status in (500, 502, 503, 504, 529):
                                stop_reason = "provider_error"
                            else:
                                stop_reason = "provider_error" if not subtype else subtype
                    else:
                        state = "completed"
                        stop_reason = _get(message, "stop_reason") or subtype or "end_turn"

                    accounting_complete = meter.is_accounting_complete()
                    break

            # Final check for accepted_source before terminal
            if not submission_emitted and spec.local_tools is not None:
                src = getattr(spec.local_tools, "accepted_source", None)
                if src:
                    submission_emitted = True
                    yield RuntimeEvent(kind="submission", data={"source": str(src)})

            if meter.is_accounting_complete():
                accounting_complete = True
            else:
                accounting_complete = False

            yield RuntimeEvent(
                kind="terminal",
                data={
                    "state": state,
                    "stop_reason": stop_reason,
                    "accounting_complete": accounting_complete,
                },
            )

        finally:
            if stream is not None:
                if hasattr(stream, "interrupt") and (session_state.cancelled or state != "completed"):
                    try:
                        res = stream.interrupt()
                        if inspect.isawaitable(res):
                            await res
                    except Exception:
                        pass
                if hasattr(stream, "aclose"):
                    try:
                        await stream.aclose()
                    except Exception:
                        pass

            if spec.local_tools is not None and hasattr(spec.local_tools, "aclose"):
                try:
                    await spec.local_tools.aclose()
                except Exception as err:
                    logger.warning("local_tools aclose error: %s", type(err).__name__)

            if owns_workdir:
                shutil.rmtree(workdir, ignore_errors=True)

            self._sessions.pop(spec.session_id, None)
