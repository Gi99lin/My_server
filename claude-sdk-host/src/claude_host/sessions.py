"""Finite queues, per-session process groups, and non-content durable event replay."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import signal
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .config import Application, Settings, read_secret
from .contracts import RunFailure
from .journal import TERMINAL_STATES, Journal


@dataclass(repr=False)
class LiveSession:
    id: str
    app_id: str
    payload: dict
    deadline: float
    accepted: float = field(default_factory=time.monotonic)
    last_ack: float = field(default_factory=time.monotonic)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    listeners: set[asyncio.Queue] = field(default_factory=set)
    process: asyncio.subprocess.Process | None = None
    task: asyncio.Task | None = None
    stop_reason: str | None = None
    submission: dict | None = None
    finished: float | None = None
    text_bytes: int = 0


class Supervisor:
    def __init__(self, settings: Settings, config_path: Path, *, worker_command: list[str] | None = None):
        self.settings = settings
        self.config_path = config_path
        self.journal = Journal(settings.journal_path, settings.max_journal_bytes)
        self.live: dict[str, LiveSession] = {}
        self.queues: dict[str, deque[str]] = {"agent": deque(), "completion": deque()}
        self.active: set[str] = set()
        self.draining = False
        self._turn = "agent"
        self._wakeup = asyncio.Event()
        self._scheduler: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._package_path = str(Path(__file__).resolve().parent.parent)
        self._worker_command = worker_command or [sys.executable, "-m", "claude_host.worker"]

    async def start(self):
        self.settings.work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.journal.cleanup()
        self._scheduler = asyncio.create_task(self._schedule())
        self._watchdog = asyncio.create_task(self._watch())

    async def close(self):
        self.draining = True
        for task in (self._scheduler, self._watchdog):
            if task:
                task.cancel()
        await asyncio.gather(
            *(self.cancel(s.id, s.app_id, "host_shutdown") for s in list(self.live.values()) if not s.done.is_set()),
            return_exceptions=True,
        )
        for task in (self._scheduler, self._watchdog):
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        running = [s.task for s in self.live.values() if s.task and not s.task.done()]
        if running:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.gather(*running, return_exceptions=True), 5)

    def stats(self) -> dict:
        return {
            "status": "ok",
            "active": len(self.active),
            "queued": sum(map(len, self.queues.values())),
            "draining": self.draining,
        }

    def metrics(self, app_id: str) -> str:
        # Labels come from fixed enums, never prompts, headers or identifiers.
        rows = []
        with self.journal.connection() as db:
            for row in db.execute(
                "SELECT state,COUNT(*) AS count,SUM(input_tokens) AS input,"
                "SUM(cache_creation_input_tokens) AS write,SUM(cache_read_input_tokens) AS read,"
                "SUM(output_tokens) AS output,"
                "SUM(COALESCE((SELECT MIN(e.created_at) FROM events e "
                "WHERE e.session_id=sessions.id AND e.kind='terminal'),updated_at)-created_at) AS duration "
                "FROM sessions WHERE app_id=? GROUP BY state",
                (app_id,),
            ):
                state = row["state"]
                rows.append(f'claude_host_sessions{{state="{state}"}} {row["count"]}')
                for kind in ("input", "write", "read", "output"):
                    rows.append(f'claude_host_tokens{{state="{state}",category="{kind}"}} {row[kind] or 0}')
                if state in TERMINAL_STATES:
                    rows.append(f'claude_host_duration_seconds_sum{{state="{state}"}} {row["duration"] or 0}')
        owned = [s for s in self.live.values() if s.app_id == app_id]
        rows.append(f"claude_host_active_children {sum(s.id in self.active for s in owned)}")
        rows.append(f"claude_host_queued {sum(not s.done.is_set() and s.id not in self.active for s in owned)}")
        return "\n".join(rows) + "\n"

    async def submit(self, app: Application, payload: dict) -> tuple[dict, bool]:
        if self.draining:
            raise RunFailure("host_draining", 503)
        if self.settings.network_ready_file and not self.settings.network_ready_file.is_file():
            raise RunFailure("host_not_ready", 503)
        profile = payload["profile"]
        category = "completion" if profile == "completion" else "agent"
        capacity = self.settings.completion_queue_size if category == "completion" else self.settings.agent_queue_size
        # Inspect an existing receipt before admission capacity; idempotent reads create no work.
        digest = hmac.new(
            read_secret(self.settings.idempotency_key_file).encode(),
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            hashlib.sha256,
        ).hexdigest()
        existing = self.journal.find_request(app.id, payload["client_request_id"])
        if existing:
            if existing["digest"] != digest:
                raise RunFailure("idempotency_conflict", 409)
            return self.get(existing["id"], app.id), False
        if len(self.queues[category]) >= capacity:
            raise RunFailure("queue_full", 429)
        sid = str(uuid.uuid4())
        timeout = payload["timeout_seconds"]
        row, created = self.journal.create(
            session_id=sid,
            app_id=app.id,
            request_id=payload["client_request_id"],
            digest=digest,
            profile=profile,
            model=payload["model"],
            expires_at=time.time() + timeout,
        )
        if created:
            live = LiveSession(sid, app.id, payload, time.monotonic() + timeout)
            self.live[sid] = live
            self.queues[category].append(sid)
            self._wakeup.set()
        return row, created

    def get(self, sid: str, app_id: str) -> dict:
        row = self.journal.get(sid, app_id)
        live = self.live.get(sid)
        if row["profile"] == "tms-authoring" and row["submission_seq"] is not None and not row["result_acknowledged"]:
            row["result_available"] = bool(live and live.submission)
        return row

    def listen(self, sid: str, app_id: str, after: int = 0) -> tuple[asyncio.Queue, list[dict]]:
        row = self.journal.get(sid, app_id)
        if after < 0 or after > row["last_seq"]:
            raise RunFailure("invalid_event_cursor", 400)
        listener: asyncio.Queue = asyncio.Queue(maxsize=256)
        live = self.live.get(sid)
        if live:
            live.listeners.add(listener)
        replay = self.journal.events(sid, app_id, after)
        if row["submission_seq"] and after < row["submission_seq"] and not row["result_acknowledged"]:
            if live and live.submission:
                replay.append(live.submission)
            else:
                self.unlisten(sid, listener)
                raise RunFailure("result_unavailable", 410)
        replay.sort(key=lambda e: e["seq"])
        return listener, replay

    def unlisten(self, sid: str, listener: asyncio.Queue):
        live = self.live.get(sid)
        if live:
            live.listeners.discard(listener)

    def ack(self, sid: str, app_id: str, seq: int) -> dict:
        row = self.journal.ack(sid, app_id, seq)
        live = self.live.get(sid)
        if live:
            live.last_ack = time.monotonic()
            if row["result_acknowledged"]:
                live.submission = None
        return row

    def _publish(self, live: LiveSession, kind: str, data: dict):
        if live.done.is_set():
            return
        if kind == "text_delta":
            if not isinstance(data.get("text"), str):
                raise RunFailure("invalid_worker_event")
            live.text_bytes += len(data["text"].encode())
            if live.text_bytes > 1_048_576:
                raise RunFailure("output_limit_exceeded")
        if kind == "submission":
            source = data.get("source")
            if (
                live.payload["profile"] != "tms-authoring"
                or not isinstance(source, str)
                or len(source) > 60000
                or live.submission
            ):
                raise RunFailure("invalid_worker_submission")
        event = self.journal.append(live.id, kind, data)
        if kind == "submission":
            live.submission = event
        for listener in tuple(live.listeners):
            try:
                listener.put_nowait(event)
            except asyncio.QueueFull:
                # A stalled subscriber must reconnect to durable accounting events.
                live.listeners.discard(listener)
                while not listener.empty():
                    listener.get_nowait()
                listener.put_nowait({"type": "disconnect", "data": {"code": "slow_consumer"}})
        if kind == "started":
            live.started.set()
        if kind == "terminal":
            live.finished = time.monotonic()
            live.payload.clear()
            live.done.set()
            live.started.set()

    async def cancel(self, sid: str, app_id: str, reason: str = "cancelled") -> dict:
        self.journal.get(sid, app_id)
        live = self.live.get(sid)
        if live is None or live.done.is_set():
            return self.get(sid, app_id)
        live.stop_reason = live.stop_reason or reason
        if live.process:
            await self._terminate(live)
        if not live.done.is_set():
            state = {
                "deadline_exceeded": "timed_out",
                "consumer_lost": "consumer_lost",
                "budget_exceeded": "budget_exceeded",
                "queue_timeout": "timed_out",
            }.get(live.stop_reason, "cancelled")
            self._publish(
                live,
                "terminal",
                {"state": state, "stop_reason": live.stop_reason, "accounting_complete": False},
            )
        for queue in self.queues.values():
            with contextlib.suppress(ValueError):
                queue.remove(sid)
        return self.get(sid, app_id)

    async def _terminate(self, live: LiveSession):
        process = live.process
        if process is None:
            return
        # Always kill the whole group, including surviving Chromium grandchildren.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=4)
        except TimeoutError:
            pass
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()

    async def _schedule(self):
        while True:
            self._wakeup.clear()
            while len(self.active) < self.settings.max_children:
                other = "completion" if self._turn == "agent" else "agent"
                category = self._turn if self.queues[self._turn] else other
                if not self.queues[category]:
                    break
                sid = self.queues[category].popleft()
                live = self.live[sid]
                self._turn = "completion" if category == "agent" else "agent"
                if live.done.is_set():
                    continue
                self.active.add(sid)
                live.task = asyncio.create_task(self._execute(live))
            await self._wakeup.wait()

    async def _execute(self, live: LiveSession):
        pending_terminal = None
        try:
            if live.done.is_set() or live.stop_reason:
                return
            if time.monotonic() >= live.deadline:
                raise RunFailure("deadline_exceeded")
            self.journal.set_running(live.id)
            env = self.settings.sdk_environment()
            # Package location is coordinator-owned, never supplied in an HTTP request.
            env["PYTHONPATH"] = self._package_path
            live.process = await asyncio.create_subprocess_exec(
                *self._worker_command,
                "--config",
                str(self.config_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
                cwd=self.settings.work_dir,
                start_new_session=True,
                limit=1_100_000,
            )
            if live.done.is_set() or live.stop_reason:
                raise RunFailure(live.stop_reason or "cancelled")
            wire = {
                "session_id": live.id,
                "remaining_seconds": max(0, live.deadline - time.monotonic()),
                "payload": live.payload,
            }
            live.process.stdin.write(json.dumps(wire, ensure_ascii=False).encode() + b"\n")
            await live.process.stdin.drain()
            live.process.stdin.close()
            while True:
                line = await live.process.stdout.readline()
                if not line:
                    break
                if len(line) > 1_048_576:
                    raise RunFailure("invalid_worker_event")
                event = json.loads(line)
                kind, data = event.get("kind"), event.get("data")
                if kind not in {
                    "started",
                    "text_delta",
                    "usage",
                    "rate_limit",
                    "submission",
                    "terminal",
                } or not isinstance(data, dict):
                    raise RunFailure("invalid_worker_event")
                if pending_terminal is not None:
                    raise RunFailure("invalid_worker_event")
                if kind == "terminal":
                    pending_terminal = data
                else:
                    self._publish(live, kind, data)
                if self.journal.disk_bytes() >= self.settings.max_journal_bytes:
                    raise RunFailure("journal_full")
            await asyncio.wait_for(live.process.wait(), timeout=5)
            if live.stop_reason:
                raise RunFailure(live.stop_reason)
            if live.process.returncode != 0 or pending_terminal is None:
                raise RunFailure("worker_interrupted")
            self._publish(live, "terminal", pending_terminal)
        except asyncio.CancelledError:
            live.stop_reason = "host_shutdown"
            raise
        except Exception as error:
            reason = live.stop_reason or (error.code if isinstance(error, RunFailure) else "worker_interrupted")
            if not live.done.is_set():
                self._publish(
                    live,
                    "terminal",
                    {
                        "state": self._failure_state(reason),
                        "stop_reason": reason,
                        "accounting_complete": False,
                    },
                )
        finally:
            await self._terminate(live)
            if not live.done.is_set():
                self._publish(
                    live,
                    "terminal",
                    {"state": "interrupted", "stop_reason": "host_shutdown", "accounting_complete": False},
                )
            self.active.discard(live.id)
            self._wakeup.set()

    @staticmethod
    def _failure_state(reason: str) -> str:
        return {
            "cancelled": "cancelled",
            "client_disconnected": "cancelled",
            "host_shutdown": "interrupted",
            "deadline_exceeded": "timed_out",
            "queue_timeout": "timed_out",
            "consumer_lost": "consumer_lost",
            "budget_exceeded": "budget_exceeded",
        }.get(reason, "failed")

    async def _watch(self):
        while True:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            for live in list(self.live.values()):
                if live.done.is_set():
                    if live.finished is not None and now - live.finished >= self.settings.submission_retention_seconds:
                        live.submission = None
                        if live.id not in self.active:
                            self.live.pop(live.id, None)
                    continue
                reason = None
                if now >= live.deadline:
                    reason = "deadline_exceeded"
                elif live.id not in self.active and now - live.accepted >= self.settings.queue_wait_seconds:
                    reason = "queue_timeout"
                elif (
                    live.payload["profile"] != "completion"
                    and now - live.last_ack >= self.settings.consumer_timeout_seconds
                ):
                    reason = "consumer_lost"
                if reason and live.stop_reason is None:
                    live.stop_reason = reason
                    asyncio.create_task(self.cancel(live.id, live.app_id, reason))
