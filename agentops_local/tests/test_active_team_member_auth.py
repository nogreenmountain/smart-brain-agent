from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_middleware_module():
    module_path = Path(
        os.environ.get(
            "AUTH_MIDDLEWARE_PATH",
            Path(__file__).parents[1] / "auth" / "middleware.py",
        )
    )
    spec = importlib.util.spec_from_file_location("agentops.auth.middleware_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load middleware module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


middleware = _load_middleware_module()


class _Result:
    def __init__(self, is_active):
        self.is_active = is_active

    def first(self):
        if self.is_active is None:
            return None
        return SimpleNamespace(is_active=self.is_active)


class _Orm:
    def __init__(self, is_active):
        self.is_active = is_active
        self.sql = ""

    def execute(self, statement, params):
        self.sql = str(statement)
        return _Result(self.is_active)


class _Session:
    def __init__(self):
        self.user_id = uuid.UUID("00000000-0000-0000-0000-000000000012")
        self.expired = False

    def expire(self):
        self.expired = True


class ActiveTeamMemberAuthTests(unittest.TestCase):
    def test_inactive_member_session_is_expired_immediately(self):
        orm = _Orm(False)

        @contextmanager
        def fake_scope():
            yield orm

        session = _Session()
        with patch.object(middleware, "session_scope", fake_scope):
            with self.assertRaises(middleware.AuthException):
                middleware._require_active_team_member(session)

        self.assertTrue(session.expired)
        self.assertIn("is_active", orm.sql)

    def test_active_member_session_continues(self):
        orm = _Orm(True)

        @contextmanager
        def fake_scope():
            yield orm

        session = _Session()
        with patch.object(middleware, "session_scope", fake_scope):
            middleware._require_active_team_member(session)

        self.assertFalse(session.expired)


if __name__ == "__main__":
    unittest.main()
