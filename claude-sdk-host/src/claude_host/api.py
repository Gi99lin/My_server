"""Private completion and agent-session APIs with safe, bounded request handling."""

from __future__ import annotations

import asyncio
import json
import signal
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from .auth import request_application
from .config import Settings, load_settings
from .contracts import RunFailure
from .journal import TERMINAL_STATES, USAGE_FIELDS
from .requests import Ack, AgentRequest, CompletionRequest, authorize_model, safe_identifier
from .sessions import Supervisor


def error_response(code: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": code, "type": "host_error"}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


class BodyLimit:
    def __init__(self, app, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Buffer at most one bounded body, including chunked requests, before JSON parsing.
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await error_response("request_too_large", 413)(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body", False):
                break

        async def bounded_receive():
            if chunks:
                return chunks.pop(0)
            return await receive()

        await self.app(scope, bounded_receive, send)


def parse_request(cls, data):
    try:
        return cls.model_validate(data)
    except ValidationError as error:
        unsupported = any(e["type"] == "extra_forbidden" for e in error.errors(include_input=False))
        raise RunFailure("unsupported_parameter" if unsupported else "invalid_request", 400) from None


def usage_response(counters: dict) -> dict:
    prompt = sum(counters.get(k, 0) for k in USAGE_FIELDS[:3])
    output = counters.get("output_tokens", 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": output,
        "total_tokens": prompt + output,
        "prompt_tokens_details": {"cached_tokens": counters.get("cache_read_input_tokens", 0)},
    }


def create_app(
    config_path: Path, *, settings: Settings | None = None, supervisor: Supervisor | None = None
) -> FastAPI:
    cfg = settings or load_settings(config_path)
    manager = supervisor or Supervisor(cfg, config_path)

    @asynccontextmanager
    async def lifespan(app):
        await manager.start()
        loop = asyncio.get_running_loop()

        def drain():
            manager.draining = True

        loop.add_signal_handler(signal.SIGUSR1, drain)
        try:
            yield
        finally:
            loop.remove_signal_handler(signal.SIGUSR1)
            await manager.close()

    app = FastAPI(
        title="Personal Claude SDK Host", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.settings, app.state.supervisor = cfg, manager
    app.add_middleware(BodyLimit, limit=cfg.max_body_bytes)

    @app.exception_handler(RunFailure)
    async def run_failure(_request, error):
        return error_response(error.code, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_failure(_request, _error):
        return error_response("invalid_request", 400)

    @app.exception_handler(Exception)
    async def unexpected_failure(_request, _error):
        return error_response("host_error", 503)

    @app.middleware("http")
    async def no_content_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    async def body(request: Request):
        try:
            return await request.json()
        except (ValueError, UnicodeError):
            raise RunFailure("invalid_request", 400) from None

    @app.get("/health/live")
    async def live():
        return manager.stats()

    @app.get("/health/ready")
    async def ready():
        if manager.draining or (cfg.network_ready_file and not cfg.network_ready_file.is_file()):
            raise RunFailure("host_not_ready", 503)
        cfg.verify_secret_files()
        # Network and auth are operator-proven prerequisites; this endpoint never makes a paid query.
        if not cfg.auth_dir.is_dir():
            raise RunFailure("auth_directory_unavailable", 503)
        return {"status": "ready", "inference_verified": False}

    @app.get("/v1/models")
    async def models(request: Request):
        application = request_application(request)
        return {
            "object": "list",
            "data": [
                {"id": model, "object": "model", "owned_by": "personal-claude"}
                for model in application.models
            ],
        }

    @app.get("/v1/capabilities")
    async def capabilities(request: Request):
        application = request_application(request)
        return {
            "scopes": application.scopes,
            "completion": {
                "text_only": True,
                "tools": False,
                "max_turns": 1,
                "parameters": ["model", "messages", "prompt", "stream", "stream_options", "n"],
                "sampling_controls": False,
            },
            "sessions": {
                "replay": ["started", "usage", "terminal"],
                "source_retention_seconds": cfg.submission_retention_seconds,
                "ack_interval_seconds": 5,
                "consumer_timeout_seconds": cfg.consumer_timeout_seconds,
            },
            "budget": {
                "agent": "input + cache_creation + output",
                "completion_prompt": "input + cache_creation + cache_read",
                "hard_token_cap": False,
            },
        }

    @app.post("/v1/agent-sessions", status_code=202)
    async def create_session(request: Request):
        application = request_application(request, "session:create")
        parsed = parse_request(AgentRequest, await body(request))
        parsed.authorize(application, cfg)
        row, created = await manager.submit(application, parsed.private_payload())
        return JSONResponse({**row, "created": created}, status_code=202 if created else 200)

    @app.get("/v1/agent-sessions/{sid}")
    async def get_session(sid: str, request: Request):
        application = request_application(request, "session:read")
        return manager.get(safe_identifier(sid), application.id)

    @app.post("/v1/agent-sessions/{sid}/ack")
    async def ack_session(sid: str, request: Request):
        application = request_application(request, "session:read")
        parsed = parse_request(Ack, await body(request))
        return manager.ack(safe_identifier(sid), application.id, parsed.seq)

    @app.post("/v1/agent-sessions/{sid}/cancel")
    async def cancel_session(sid: str, request: Request):
        application = request_application(request, "session:cancel")
        return await manager.cancel(safe_identifier(sid), application.id)

    @app.get("/v1/agent-sessions/{sid}/events")
    async def events(sid: str, request: Request):
        application = request_application(request, "session:read")
        safe_identifier(sid)
        cursor = request.headers.get("last-event-id")
        try:
            if cursor:
                owner, number = cursor.rsplit(":", 1)
                if owner != sid:
                    raise ValueError
                after = int(number)
            else:
                after = int(request.query_params.get("after", "0"))
        except ValueError:
            raise RunFailure("invalid_event_cursor", 400) from None
        listener, replay = manager.listen(sid, application.id, after)

        async def stream():
            last = after
            try:
                for event in replay:
                    last = max(last, event["seq"])
                    yield sse(event)
                while (
                    manager.get(sid, application.id)["state"] not in TERMINAL_STATES or not listener.empty()
                ):
                    try:
                        event = await asyncio.wait_for(listener.get(), timeout=5)
                    except TimeoutError:
                        yield ": heartbeat\n\n"
                        continue
                    if event["type"] == "disconnect":
                        yield 'event: error\ndata: {"code":"slow_consumer"}\n\n'
                        break
                    if event["seq"] > last:
                        last = event["seq"]
                        yield sse(event)
            finally:
                manager.unlisten(sid, listener)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    def sse(event):
        return (
            f"id: {event['event_id']}\nevent: {event['type']}\n"
            f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        )

    async def completion(request: Request, chat: bool):
        application = request_application(request, "completion")
        parsed = parse_request(CompletionRequest, await body(request))
        authorize_model(parsed.model, application, cfg)
        system, prompt = parsed.conversation(chat)
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "profile": "completion",
            "model": parsed.model,
            "system_prompt": system,
            "prompt": prompt,
            "max_turns": 1,
            "timeout_seconds": cfg.completion_timeout_seconds,
            "token_budget": cfg.max_agent_tokens,
        }
        row, _ = await manager.submit(application, payload)
        sid = row["id"]
        listener, replay = manager.listen(sid, application.id)
        # Attach before yielding to scheduler so text cannot race past the listener.
        live_session = manager.live[sid]
        created = int(time.time())
        identifier = f"{'chatcmpl' if chat else 'cmpl'}-{sid}"
        response_kind = "chat.completion" if chat else "text_completion"

        def chunk(text=None, finish=None, *, role=False, usage=None):
            delta = ({"role": "assistant"} if role else {"content": text}) if chat else None
            result = {
                "id": identifier,
                "object": "chat.completion.chunk" if chat else "text_completion",
                "created": created,
                "model": parsed.model,
                "choices": []
                if usage is not None
                else [
                    {
                        "index": 0,
                        **({"delta": delta or {}} if chat else {"text": text or "", "logprobs": None}),
                        "finish_reason": finish,
                    }
                ],
            }
            if usage is not None:
                result["usage"] = usage
            return "data: " + json.dumps(result, ensure_ascii=False) + "\n\n"

        async def next_event():
            while True:
                if await request.is_disconnected():
                    raise RunFailure("client_disconnected", 499)
                try:
                    return await asyncio.wait_for(listener.get(), timeout=0.25)
                except TimeoutError:
                    if live_session.done.is_set() and listener.empty():
                        raise RunFailure("worker_interrupted") from None

        async def settle():
            result = manager.get(sid, application.id)
            manager.ack(sid, application.id, result["last_seq"])
            if result["state"] != "completed":
                raise RunFailure(
                    result["stop_reason"] or "completion_failed",
                    429 if result["stop_reason"] == "rate_limited" else 503,
                )
            return result

        if not parsed.stream:
            text_parts = []
            try:
                while True:
                    event = await next_event()
                    if event["type"] == "text_delta":
                        text_parts.append(event["data"]["text"])
                    elif event["type"] == "terminal":
                        result = await settle()
                        choice = {
                            "index": 0,
                            "finish_reason": "length" if result["stop_reason"] == "max_turns" else "stop",
                        }
                        choice.update(
                            {"message": {"role": "assistant", "content": "".join(text_parts)}}
                            if chat
                            else {"text": "".join(text_parts), "logprobs": None}
                        )
                        return {
                            "id": identifier,
                            "object": response_kind,
                            "created": created,
                            "model": parsed.model,
                            "choices": [choice],
                            "usage": usage_response(result["usage"]),
                        }
            finally:
                manager.unlisten(sid, listener)
                if not live_session.done.is_set():
                    await manager.cancel(sid, application.id, "client_disconnected")

        # Delay HTTP headers until SDK startup or a concrete pre-start failure.
        try:
            while True:
                event = await next_event()
                if event["type"] == "started":
                    break
                if event["type"] == "terminal":
                    await settle()
                    raise RunFailure("provider_stream_incomplete")
        except BaseException:
            manager.unlisten(sid, listener)
            if not live_session.done.is_set():
                await manager.cancel(sid, application.id, "client_disconnected")
            raise

        async def stream_completion():
            try:
                if chat:
                    yield chunk(role=True)
                while True:
                    event = await next_event()
                    if event["type"] == "text_delta":
                        yield chunk(event["data"]["text"])
                    elif event["type"] == "terminal":
                        result = await settle()
                        yield chunk(finish="length" if result["stop_reason"] == "max_turns" else "stop")
                        if parsed.stream_options and parsed.stream_options.include_usage:
                            yield chunk(usage=usage_response(result["usage"]))
                        yield "data: [DONE]\n\n"
                        break
            except RunFailure as error:
                yield "data: " + json.dumps({"error": {"code": error.code, "message": error.code}}) + "\n\n"
            finally:
                manager.unlisten(sid, listener)
                if not live_session.done.is_set():
                    await manager.cancel(sid, application.id, "client_disconnected")

        return StreamingResponse(
            stream_completion(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.post("/v1/chat/completions")
    async def chat_completion(request: Request):
        return await completion(request, True)

    @app.post("/v1/completions")
    async def text_completion(request: Request):
        return await completion(request, False)

    return app
