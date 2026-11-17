"""Candidate-image checks against the pilot's real authenticated Shellctl.

Only disposable directories under /workspace are used. Run this file on the
pilot sandbox Docker network, mounting its token at /run/sandbox-token.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import uuid
from pathlib import Path

import pytest
from shellctl.client import ShellctlClient

from dify_agent.adapters.shell.shellctl import ShellctlCommands
from test_cancellation import invoke, make_session
from tests.local.dify_agent.layers.shell.test_layer import _parse_tagged_observation


class GatedCommands:
    """Delay a real creation reply or cleanup to exercise cancellation windows."""

    def __init__(self, client, phase):
        self.commands = ShellctlCommands(client)
        self.phase = phase
        self.created = asyncio.Event()
        self.waiting = asyncio.Event()
        self.deleting = asyncio.Event()
        self.response_gate = asyncio.Event()
        self.delete_gate = asyncio.Event()
        if not phase.startswith("creation"):
            self.response_gate.set()
        if phase not in ("cleanup_repeated", "late_cleanup", "late_cleanup_repeated"):
            self.delete_gate.set()

    async def run(self, *args, **kwargs):
        result = await self.commands.run(*args, **kwargs)
        self.created.set()
        await self.response_gate.wait()
        return result

    async def wait(self, *args, **kwargs):
        self.waiting.set()
        return await self.commands.wait(*args, **kwargs)

    async def delete(self, *args, **kwargs):
        self.deleting.set()
        await self.delete_gate.wait()
        return await self.commands.delete(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.commands, name)


def make_client():
    token_file = os.environ.get("SHELLCTL_TOKEN_FILE", "/run/sandbox-token")
    endpoint = os.environ.get("SHELLCTL_URL", "http://local_sandbox:5004")
    return ShellctlClient(endpoint, token=Path(token_file).read_text().strip())


async def control(client, script):
    result = await client.run(script, cwd="/workspace", timeout=2)
    try:
        while not result.done:
            result = await client.wait(result.job_id, offset=0, timeout=2)
        return result
    finally:
        await client.delete(result.job_id, force=True)


@pytest.mark.parametrize("phase", [
    "initial_wait", "creation", "creation_repeated", "cleanup_repeated",
    "late_cleanup", "late_cleanup_repeated",
])
def test_live_cancellation_prevents_delayed_process_tree_side_effects(phase):
    async def scenario():
        client = make_client()
        directory = "/workspace/cancel-fix-" + uuid.uuid4().hex
        marker = directory + "/must-not-exist.txt"
        child_ready = directory + "/child-ready.txt"
        created = await control(client, "mkdir -p " + shlex.quote(directory))
        assert created.exit_code == 0
        commands = GatedCommands(client, phase)
        layer = make_session(commands, Path(directory))
        # A separate Python child would write the marker if its process group
        # survived cancellation. This checks more than the HTTP stop response.
        child = (
            f"import time,pathlib; pathlib.Path({child_ready!r}).write_text('READY'); "
            f"time.sleep(3); pathlib.Path({marker!r}).write_text('ORPHAN')"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
        )
        task = asyncio.create_task(invoke(
            layer, "python3 -c " + shlex.quote(parent),
            timeout=0.001 if "cleanup" in phase else 30,
            wait_after_start=phase == "cleanup_repeated",
        ))
        try:
            if phase.startswith("late_cleanup"):
                ready = commands.deleting
            else:
                ready = commands.created if phase.startswith("creation") else commands.waiting
            await asyncio.wait_for(ready.wait(), 10)
            # Prove that a descendant is already alive; killing only the
            # launching parent before it forks would be an insufficient check.
            async with asyncio.timeout(5):
                while True:
                    result = await control(client, "test -e " + shlex.quote(child_ready))
                    if result.exit_code == 0:
                        break
                    await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0)
            if phase == "cleanup_repeated":
                await asyncio.wait_for(commands.deleting.wait(), 10)
            if phase.endswith("repeated"):
                task.cancel()
                await asyncio.sleep(0)
            commands.response_gate.set()
            commands.delete_gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 10)
            await asyncio.sleep(3.5)
            result = await control(client, "test ! -e " + shlex.quote(marker))
            assert result.exit_code == 0, f"{phase}: a canceled process tree still wrote its marker"
        finally:
            commands.response_gate.set()
            commands.delete_gate.set()
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            cleanup = "import shutil; shutil.rmtree(" + repr(directory) + ", ignore_errors=True)"
            await control(client, "python3 -c " + shlex.quote(cleanup))
            await client.close()

    asyncio.run(scenario())


def test_live_normal_command_output_and_completion_are_preserved():
    async def scenario():
        client = make_client()
        directory = "/workspace/cancel-fix-" + uuid.uuid4().hex
        result = await control(client, "mkdir -p " + shlex.quote(directory))
        assert result.exit_code == 0
        try:
            layer = make_session(GatedCommands(client, "normal"), Path(directory))
            output = await invoke(layer, "printf LIVE_NORMAL_OK", timeout=2)
            metadata, text = _parse_tagged_observation(output)
            assert metadata["done"] is True
            assert metadata["exit_code"] == 0
            assert text == "LIVE_NORMAL_OK"
        finally:
            cleanup = "import shutil; shutil.rmtree(" + repr(directory) + ", ignore_errors=True)"
            await control(client, "python3 -c " + shlex.quote(cleanup))
            await client.close()

    asyncio.run(scenario())
