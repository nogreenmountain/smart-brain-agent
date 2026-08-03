from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Callable

from mcp.server.auth.provider import AccessToken

try:
    from sqlalchemy import text
except ModuleNotFoundError:  # Standalone unit tests do not install SQLAlchemy.
    def text(value: str) -> str:
        return value

try:
    from agentops.project_wiki.tokens import TOKEN_PREFIX, hash_token
except ModuleNotFoundError:  # Standalone unit tests load this module directly.
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).parents[1] / "project_wiki" / "tokens.py"
    spec = importlib.util.spec_from_file_location("wiki_mcp_tokens_for_auth", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load token helpers from {path}")
    token_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = token_module
    spec.loader.exec_module(token_module)
    TOKEN_PREFIX = token_module.TOKEN_PREFIX
    hash_token = token_module.hash_token


SessionFactory = Callable[[], AbstractContextManager]


def _epoch(value: datetime | None) -> int | None:
    if value is None:
        return None
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return int(timestamp.timestamp())


class WikiTokenVerifier:
    """Validate manually issued SmartBrain MCP bearer tokens."""

    def __init__(self, *, secret: str, session_factory: SessionFactory) -> None:
        value = str(secret or "").strip()
        if not value:
            raise ValueError("Wiki MCP token secret is required")
        self.secret = value
        self.session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        if not str(token or "").startswith(TOKEN_PREFIX):
            return None
        return await asyncio.to_thread(self._verify_sync, token)

    def _verify_sync(self, token: str) -> AccessToken | None:
        digest = hash_token(token, secret=self.secret)
        with self.session_factory() as orm:
            row = orm.execute(
                text("""
                    UPDATE public.wiki_mcp_tokens
                    SET last_used_at = now()
                    WHERE token_hash = :token_hash
                      AND revoked_at IS NULL
                      AND (expires_at IS NULL OR expires_at > now())
                    RETURNING id::text, user_id::text, scopes, expires_at
                """),
                {"token_hash": digest},
            ).first()
        if row is None:
            return None
        return AccessToken(
            token=token,
            client_id=str(row.id),
            subject=str(row.user_id),
            scopes=[str(item) for item in (row.scopes or [])],
            expires_at=_epoch(row.expires_at),
            claims={"iss": "smartbrain-wiki"},
        )
