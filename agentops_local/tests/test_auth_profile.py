from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


def _load_route_module():
    route_path = Path(
        os.environ.get(
            "AUTH_ME_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "auth_me.py",
        )
    )
    spec = importlib.util.spec_from_file_location("auth_me_route_under_test", route_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class _Result:
    def __init__(self, *, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def first(self):
        return self._first

    def all(self):
        return self._rows


class _ProfileOrm:
    def __init__(self, *, nickname=None, password_matches=True, detail_visible_to_admin=False):
        self.nickname = nickname
        self.password_matches = password_matches
        self.detail_visible_to_admin = detail_visible_to_admin
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "FROM auth.users au" in sql:
            email = "test1@local.dev"
            return _Result(
                first=SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000011",
                    email=email,
                    full_name="test1",
                    nickname=self.nickname,
                    display_name=self.nickname or email,
                    ai_detail_visible_to_admin=self.detail_visible_to_admin,
                    avatar_url=None,
                )
            )
        if "FROM public.user_orgs" in sql:
            return _Result(rows=[])
        if "encrypted_password = crypt" in sql:
            return _Result(first=SimpleNamespace(ok=1) if self.password_matches else None)
        if "ai_detail_visible_to_admin" in sql and "INSERT INTO public.users" in sql:
            self.nickname = params["nickname"]
            self.detail_visible_to_admin = params["ai_detail_visible_to_admin"]
        return _Result()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _request():
    return SimpleNamespace(
        state=SimpleNamespace(
            session=SimpleNamespace(
                user_id=uuid.UUID("00000000-0000-0000-0000-000000000011")
            )
        ),
        client=None,
    )


class AuthProfileTests(unittest.TestCase):
    def test_me_uses_email_until_nickname_is_set(self) -> None:
        response = route.auth_me(request=_request(), orm=_ProfileOrm())

        self.assertIsNone(response.nickname)
        self.assertEqual(response.display_name, "test1@local.dev")

    def test_profile_update_trims_nickname_and_returns_it_as_display_name(self) -> None:
        orm = _ProfileOrm(nickname="研发小王")
        with patch.object(route, "record_audit") as audit:
            response = route.update_profile(
                request=_request(),
                body=route.UpdateProfileRequest(
                    nickname="  研发小王  ",
                    ai_detail_visible_to_admin=False,
                ),
                orm=orm,
            )

        update_sql, update_params = next(
            (sql, params)
            for sql, params in orm.calls
            if "INSERT INTO public.users" in sql and "nickname = EXCLUDED.nickname" in sql
        )
        self.assertIn("public.users", update_sql)
        self.assertEqual(update_params["nickname"], "研发小王")
        self.assertEqual(response.display_name, "研发小王")
        audit.assert_called_once()

    def test_profile_update_saves_ai_detail_visibility_preference(self) -> None:
        orm = _ProfileOrm(nickname="唐伟翔", detail_visible_to_admin=False)
        with patch.object(route, "record_audit"):
            response = route.update_profile(
                request=_request(),
                body=route.UpdateProfileRequest(
                    nickname="唐伟翔",
                    ai_detail_visible_to_admin=True,
                ),
                orm=orm,
            )

        update_sql, update_params = next(
            (sql, params)
            for sql, params in orm.calls
            if "INSERT INTO public.users" in sql and "ai_detail_visible_to_admin" in sql
        )
        self.assertIn("ai_detail_visible_to_admin", update_sql)
        self.assertTrue(update_params["ai_detail_visible_to_admin"])
        self.assertTrue(response.ai_detail_visible_to_admin)

    def test_password_change_requires_the_current_password(self) -> None:
        orm = _ProfileOrm(password_matches=False)

        with self.assertRaises(HTTPException) as caught:
            route.change_password(
                request=_request(),
                body=route.ChangePasswordRequest(
                    current_password="wrong-password",
                    new_password="new-password-123",
                ),
                orm=orm,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertFalse(any("SET encrypted_password" in sql for sql, _ in orm.calls))

    def test_password_change_hashes_new_password_and_audits_without_secrets(self) -> None:
        orm = _ProfileOrm(password_matches=True)
        with patch.object(route, "record_audit") as audit:
            response = route.change_password(
                request=_request(),
                body=route.ChangePasswordRequest(
                    current_password="old-password-123",
                    new_password="new-password-123",
                ),
                orm=orm,
            )

        password_sql, password_params = next(
            (sql, params) for sql, params in orm.calls if "SET encrypted_password" in sql
        )
        compact_sql = " ".join(password_sql.split())
        self.assertIn("crypt( CAST(:new_password AS text), gen_salt('bf') )", compact_sql)
        self.assertEqual(password_params["new_password"], "new-password-123")
        self.assertEqual(response.status, "updated")
        audit_payload = audit.call_args.kwargs
        self.assertNotIn("password", str(audit_payload.get("metadata", {})).lower())


if __name__ == "__main__":
    unittest.main()
