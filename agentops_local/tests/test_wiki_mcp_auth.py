from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    @dataclass
    class AccessToken:
        token: str
        client_id: str
        scopes: list[str]
        expires_at: int | None = None
        resource: str | None = None
        subject: str | None = None
        claims: dict | None = None

    provider = type(sys)("mcp.server.auth.provider")
    provider.AccessToken = AccessToken
    sys.modules["mcp"] = type(sys)("mcp")
    sys.modules["mcp.server"] = type(sys)("mcp.server")
    sys.modules["mcp.server.auth"] = type(sys)("mcp.server.auth")
    sys.modules["mcp.server.auth.provider"] = provider
    path = Path(__file__).parents[1] / "wiki_mcp" / "auth.py"
    spec = importlib.util.spec_from_file_location("wiki_mcp_auth_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row


class _Orm:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result(self.row)


class WikiMcpAuthTests(unittest.TestCase):
    def test_valid_token_returns_user_identity_and_scopes(self) -> None:
        module = _load_module()
        orm = _Orm(SimpleNamespace(
            id="00000000-0000-0000-0000-000000000050",
            user_id="00000000-0000-0000-0000-000000000001",
            scopes=["wiki:read", "wiki:propose"],
            expires_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        ))

        @contextmanager
        def session_factory():
            yield orm

        verifier = module.WikiTokenVerifier(
            secret="server-secret",
            session_factory=session_factory,
        )
        token = asyncio.run(verifier.verify_token("sbmcp_visible-token"))

        self.assertIsNotNone(token)
        self.assertEqual(token.subject, "00000000-0000-0000-0000-000000000001")
        self.assertEqual(token.scopes, ["wiki:read", "wiki:propose"])
        self.assertTrue(any("last_used_at" in sql for sql, _ in orm.calls))

    def test_unknown_or_wrong_prefix_token_is_rejected(self) -> None:
        module = _load_module()
        orm = _Orm(None)

        @contextmanager
        def session_factory():
            yield orm

        verifier = module.WikiTokenVerifier(
            secret="server-secret",
            session_factory=session_factory,
        )

        self.assertIsNone(asyncio.run(verifier.verify_token("not-a-wiki-token")))
        self.assertEqual(orm.calls, [])
        self.assertIsNone(asyncio.run(verifier.verify_token("sbmcp_missing")))


if __name__ == "__main__":
    unittest.main()
