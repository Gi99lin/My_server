"""Application-scoped host authentication, separate from the Claude subscription."""

from __future__ import annotations

import secrets

from fastapi import Request

from .config import Application, Settings, read_secret
from .contracts import RunFailure


def authenticate(settings: Settings, authorization: str | None, scope: str | None = None) -> Application:
    if not authorization or not authorization.startswith("Bearer "):
        raise RunFailure("invalid_application_token", 401)
    candidate = authorization[7:]
    match: Application | None = None
    for app in settings.applications:
        if secrets.compare_digest(candidate.encode(), read_secret(app.token_file).encode()):
            match = app
    if match is None:
        raise RunFailure("invalid_application_token", 401)
    if scope is not None and scope not in match.scopes:
        raise RunFailure("insufficient_scope", 403)
    return match


def request_application(request: Request, scope: str | None = None) -> Application:
    return authenticate(request.app.state.settings, request.headers.get("authorization"), scope)
