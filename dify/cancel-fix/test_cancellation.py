"""Regression checks for shell cancellation, using real disposable subprocesses.

Run inside the pinned Agent Backend image with upstream tests mounted at
/checks/tests and this file at /checks/test_cancellation.py. No service secrets
or live model calls are needed.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from shellctl.shared.schemas import RunJobRequest
from shellctl.shared.constants import DEFAULT_TERMINATE_GRACE_SECONDS

from dify_agent.adapters.shell.protocols import ShellCommandResult
from dify_agent.layers.shell import layer as shell_module
from dify_agent.runtime_backend import RuntimeLayout
from tests.local.dify_agent.layers.shell.test_layer import (
    FakeCommands,
    _bind_execution_context,
    _layer,
    _parse_tagged_observation,
)


class ProcessCommands:
    """A command transport with Shellctl's start/initial-wait boundary.

    It starts a real process group and can delay the creation response. A
    canceled client wait deliberately does not kill the remote process; the
    production shell capability must account for and delete that job.
    """

    def __init__(self, *, delayed_response: bool = False, delayed_delete: bool = False):
        self.created = asyncio.Event()
        self.waiting = asyncio.Event()
        self.followup_waiting = asyncio.Event()
        self.response_gate = asyncio.Event()
        if not delayed_response:
            self.response_gate.set()
        self.deleting = asyncio.Event()
        self.delete_gate = asyncio.Event()
        if not delayed_delete:
            self.delete_gate.set()
        self.process: asyncio.subprocess.Process | None = None
        self.reader: asyncio.Task | None = None
        self.job_id = "regression-process"

    async def run(self, script, *, cwd=None, env=None, timeout, mode="pty"):
        # Use the actual SDK boundary validation, including its positive timeout.
        RunJobRequest(script=script, cwd=cwd, env=env, timeout=timeout, mode=mode)
        self.process = await asyncio.create_subprocess_exec(
            "/bin/sh", "-c", script,
            cwd=cwd, env={**os.environ, **(env or {})},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self.reader = asyncio.create_task(self.process.communicate())
        self.created.set()
        await self.response_gate.wait()
        return await self._observe(timeout, 0)

    async def wait(self, job_id, *, offset, timeout):
        assert job_id == self.job_id
        self.followup_waiting.set()
        return await self._observe(timeout, offset)

    async def read_output(self, job_id, *, offset):
        assert job_id == self.job_id
        return self._result(offset)

    async def tail(self, job_id):
        assert job_id == self.job_id
        return self._result(0)

    async def _observe(self, timeout, offset):
        assert self.reader is not None
        if timeout > 0:
            self.waiting.set()
            try:
                await asyncio.wait_for(asyncio.shield(self.reader), timeout)
            except TimeoutError:
                pass
        return self._result(offset)

    def _result(self, offset):
        assert self.process is not None and self.reader is not None
        done = self.reader.done()
        output = self.reader.result()[0] if done else b""
        return ShellCommandResult(
            job_id=self.job_id, status="exited" if done else "running",
            done=done, exit_code=self.process.returncode if done else None,
            output=output[offset:].decode(), offset=len(output), truncated=False,
        )

    async def delete(self, job_id, *, force=False, grace_seconds=None):
        assert job_id == self.job_id and force
        self.deleting.set()
        await self.delete_gate.wait()
        if self.process is not None:
            grace = DEFAULT_TERMINATE_GRACE_SECONDS if grace_seconds is None else grace_seconds
            if grace > 0 and self.reader is not None and not self.reader.done():
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(asyncio.shield(self.reader), grace)
                except TimeoutError:
                    pass
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self.process.wait()
        if self.reader is not None:
            await self.reader

    async def dispose(self):
        self.delete_gate.set()
        await self.delete(self.job_id, force=True, grace_seconds=0)


def make_session(commands: ProcessCommands, directory: Path):
    layer, fixture = _layer(commands=cast(FakeCommands, commands))
    _bind_execution_context(layer)
    fixture.resource.layout = RuntimeLayout(
        home_dir=str(directory), workspace_dir=str(directory),
    )
    state = layer.runtime_state
    state.initialized = True
    layer.save_state(state)
    return layer


async def invoke(layer, script, *, timeout=30.0, wait_after_start=False, finish_after_ready=None):
    capability = shell_module.Capability("shell")

    async def handler():
        session = layer.deps.resources.shells["shell"]
        result = await session._tool_run(script, timeout=timeout)
        if wait_after_start:
            metadata, _ = _parse_tagged_observation(result)
            return await session._tool_wait(metadata["job_id"], timeout=30.0)
        if finish_after_ready is not None:
            async with asyncio.timeout(2):
                while not finish_after_ready.exists():
                    await asyncio.sleep(0.005)
        return result

    return await capability.wrap_run(SimpleNamespace(deps=layer.deps), handler=handler)


def test_cancellation_during_initial_wait_terminates_the_started_process(tmp_path):
    async def scenario():
        commands = ProcessCommands()
        layer = make_session(commands, tmp_path)
        task = asyncio.create_task(invoke(layer, "sleep 30"))
        try:
            await asyncio.wait_for(commands.waiting.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert commands.process is not None
            assert commands.process.returncode is not None, "Canceled run left its process alive"
        finally:
            await commands.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("repeat_cancel", [False, True])
def test_cancellation_before_creation_reply_still_cleans_up_the_process(tmp_path, repeat_cancel):
    async def scenario():
        commands = ProcessCommands(delayed_response=True)
        layer = make_session(commands, tmp_path)
        task = asyncio.create_task(invoke(layer, "sleep 30"))
        try:
            await asyncio.wait_for(commands.created.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            if repeat_cancel:
                task.cancel()
                await asyncio.sleep(0)
            commands.response_gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert commands.process is not None
            assert commands.process.returncode is not None, "Creation cancellation orphaned a process"
        finally:
            commands.response_gate.set()
            await commands.dispose()

    asyncio.run(scenario())


def test_repeated_cancellation_cannot_interrupt_process_cleanup(tmp_path):
    async def scenario():
        commands = ProcessCommands(delayed_delete=True)
        layer = make_session(commands, tmp_path)
        task = asyncio.create_task(invoke(layer, "sleep 30", timeout=0.001, wait_after_start=True))
        try:
            await asyncio.wait_for(commands.followup_waiting.wait(), 2)
            task.cancel()
            await asyncio.wait_for(commands.deleting.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            commands.delete_gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert commands.process is not None
            assert commands.process.returncode is not None, "Repeated cancellation interrupted cleanup"
        finally:
            await commands.dispose()

    asyncio.run(scenario())


def test_cancellation_does_not_leave_a_grace_period_for_an_ignoring_child(tmp_path):
    async def scenario():
        commands = ProcessCommands()
        layer = make_session(commands, tmp_path)
        ready = tmp_path / "signal-handler-ready"
        program = (
            "import signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"Path({str(ready)!r}).write_text('ready'); time.sleep(30)"
        )
        task = asyncio.create_task(invoke(layer, "python -c " + shlex.quote(program)))
        try:
            async with asyncio.timeout(2):
                while not ready.exists():
                    await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert commands.process is not None
            assert commands.process.returncode is not None
        finally:
            await commands.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("repeat_cancel", [False, True])
def test_first_cancellation_during_normal_cleanup_cannot_leave_a_live_child(tmp_path, repeat_cancel):
    async def scenario():
        commands = ProcessCommands(delayed_delete=True)
        layer = make_session(commands, tmp_path)
        ready = tmp_path / "normal-handler-ready"
        marker = tmp_path / "must-not-exist"
        program = (
            "import signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"Path({str(ready)!r}).write_text('ready'); time.sleep(0.3); "
            f"Path({str(marker)!r}).write_text('ORPHAN'); time.sleep(30)"
        )
        task = asyncio.create_task(invoke(
            layer, "python -c " + shlex.quote(program),
            timeout=0.001, finish_after_ready=ready,
        ))
        try:
            # The handler has returned successfully while its job is still alive.
            await asyncio.wait_for(commands.deleting.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            if repeat_cancel:
                task.cancel()
                await asyncio.sleep(0)
            commands.delete_gate.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            await asyncio.sleep(0.4)
            assert not marker.exists(), "Late cancellation allowed a child side effect"
        finally:
            await commands.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("exit_code", [0, 7])
def test_normal_completion_preserves_output_and_exit_status(tmp_path, exit_code):
    async def scenario():
        commands = ProcessCommands()
        layer = make_session(commands, tmp_path)
        try:
            result = await invoke(
                layer, f"printf 'first\\n'; sleep 0.02; printf 'last\\n'; exit {exit_code}",
            )
            metadata, output = _parse_tagged_observation(result)
            assert output == "first\nlast\n"
            assert metadata["done"] is True
            assert metadata["exit_code"] == exit_code
        finally:
            await commands.dispose()

    asyncio.run(scenario())
