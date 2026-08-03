from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone


TOKEN_PREFIX = "sbmcp_"


def hash_token(token: str, *, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_token(*, secret: str) -> tuple[str, str]:
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_token(raw, secret=secret)


def token_record_is_active(
    *,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if revoked_at is not None:
        return False
    if expires_at is not None:
        expiry = expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= current:
            return False
    return True
