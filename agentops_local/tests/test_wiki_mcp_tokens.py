from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_tokens():
    path = Path(__file__).parents[1] / "project_wiki" / "tokens.py"
    spec = importlib.util.spec_from_file_location("wiki_mcp_tokens_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WikiMcpTokenTests(unittest.TestCase):
    def test_issued_token_is_prefixed_and_only_hash_is_persisted(self) -> None:
        tokens = _load_tokens()

        raw, digest = tokens.issue_token(secret="server-secret")

        self.assertTrue(raw.startswith("sbmcp_"))
        self.assertNotIn(raw, digest)
        self.assertEqual(digest, tokens.hash_token(raw, secret="server-secret"))

    def test_expired_or_revoked_token_record_is_not_active(self) -> None:
        tokens = _load_tokens()
        now = datetime(2026, 8, 3, tzinfo=timezone.utc)

        self.assertFalse(tokens.token_record_is_active(
            expires_at=now - timedelta(seconds=1),
            revoked_at=None,
            now=now,
        ))
        self.assertFalse(tokens.token_record_is_active(
            expires_at=now + timedelta(days=1),
            revoked_at=now,
            now=now,
        ))
        self.assertTrue(tokens.token_record_is_active(
            expires_at=now + timedelta(days=1),
            revoked_at=None,
            now=now,
        ))


if __name__ == "__main__":
    unittest.main()
