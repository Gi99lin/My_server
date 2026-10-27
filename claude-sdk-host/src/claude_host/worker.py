"""Trusted per-session worker. Private session input arrives only over stdin."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import signal
import sys
import time
from pathlib import Path

from .config import load_settings
from .contracts import RunFailure, RunSpec


async def run(config_path: Path):
    from .runtime import SDKRunner

    output = sys.stdout

    def emit(kind: str, data: dict):
        output.write(
            json.dumps({"kind": kind, "data": data}, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        output.flush()

    runner = None
    sid = None
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        settings = load_settings(config_path)
        line = await asyncio.to_thread(sys.stdin.buffer.readline, settings.max_body_bytes + 16384)
        wire = json.loads(line)
        sid = wire["session_id"]
        payload = wire["payload"]
        profile = payload["profile"]
        local_tools = None
        mcp = {}
        allowed = []
        if profile != "completion":
            from .sdk_tools import SessionTools

            browser = payload["browser"]
            provider = settings.credential_providers[browser["credential_provider"]].model_dump(mode="json")
            provider.update(proxy_url=settings.proxy_url, proxy_bypass=settings.proxy_bypass)
            local_browser = {
                "origin": browser["origin"],
                "address": browser["origin"],
                "credential_key": browser["credential_key"],
                "lease_token": browser["credential_lease"],
                "proxy_url": settings.proxy_url,
                "proxy_bypass": settings.proxy_bypass,
            }
            execution = None
            for server in payload["mcp_servers"]:
                mcp[server["name"]] = {
                    "type": "http",
                    "url": server["url"],
                    "headers": {"Authorization": f"PrivateToken {server['token']}"},
                }
                allowed.extend(f"mcp__{server['name']}__{tool}" for tool in server["tools"])
                execution = {
                    "url": server["url"],
                    "token": server["token"],
                    "proxy_url": settings.proxy_url,
                    "proxy_bypass": settings.proxy_bypass,
                }
            source_contract = payload.get("source_contract")
            if source_contract:
                source_contract = {**source_contract, "path": source_contract["file_path"]}
            local_tools = SessionTools.from_payload(local_browser, provider, execution, source_contract)
        runner = SDKRunner(environment=settings.sdk_environment())
        spec = RunSpec(
            session_id=sid,
            model=settings.models[payload["model"]],
            system_prompt=payload["system_prompt"],
            prompt=payload["prompt"],
            max_turns=payload["max_turns"],
            deadline_monotonic=time.monotonic() + wire["remaining_seconds"],
            token_budget_remaining=payload["token_budget"],
            profile=profile,
            mcp_servers=mcp,
            allowed_tools=allowed,
            local_tools=local_tools,
        )
        # Third-party libraries must not corrupt the private NDJSON protocol.
        with contextlib.redirect_stdout(sys.stderr):
            async for event in runner.run(spec):
                emit(event.kind, event.data)
    except asyncio.CancelledError:
        if runner and sid:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(runner.cancel(sid), 1)
        emit("terminal", {"state": "cancelled", "stop_reason": "cancelled", "accounting_complete": False})
    except Exception as error:
        emit(
            "terminal",
            {
                "state": "failed",
                "stop_reason": error.code if isinstance(error, RunFailure) else "worker_failed",
                "accounting_complete": False,
            },
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
