from __future__ import annotations

import importlib.util
import os
import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_route_module():
    route_path = Path(
        os.environ.get(
            "TEAM_MEMBERS_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "team_members.py",
        )
    )
    spec = importlib.util.spec_from_file_location("team_members_route_under_test", route_path)
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


class _TeamOrm:
    caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    target_id = uuid.UUID("00000000-0000-0000-0000-000000000012")

    def __init__(self, *, target_active=True, target_system_admin=False):
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.commits = 0
        self.target_active = target_active
        self.target_system_admin = target_system_admin

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.sql.append(sql)
        self.params.append(values)
        if "WHERE au.id = :user_id" in sql:
            return _Result(
                first=SimpleNamespace(
                    user_id=str(self.target_id),
                    email="member@local.dev",
                    username="member",
                    nickname="团队成员",
                    display_name="团队成员",
                    is_active=self.target_active,
                    is_system_admin=self.target_system_admin,
                    project_count=2,
                    created_at="2026-08-02 09:00:00+00",
                    deactivated_at=None,
                )
            )
        if "COUNT(pm.project_id)" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(
                        user_id=str(self.caller_id),
                        email="admin@local.dev",
                        username="admin",
                        nickname="系统管理员",
                        display_name="系统管理员",
                        is_active=True,
                        is_system_admin=True,
                        project_count=3,
                        created_at="2026-08-01 09:00:00+00",
                        deactivated_at=None,
                    ),
                    SimpleNamespace(
                        user_id=str(self.target_id),
                        email="member@local.dev",
                        username="member",
                        nickname=None,
                        display_name="member",
                        is_active=False,
                        is_system_admin=False,
                        project_count=0,
                        created_at="2026-08-02 09:00:00+00",
                        deactivated_at="2026-08-11 09:00:00+00",
                    ),
                ]
            )
        if "WHERE lower(au.email) = lower(:email)" in sql:
            return _Result(first=None)
        if "INSERT INTO auth.users" in sql:
            return _Result(
                first=SimpleNamespace(
                    id=str(self.target_id),
                    email=values["email"],
                    created_at="2026-08-11 09:00:00+00",
                )
            )
        if "SELECT id FROM auth.users" in sql:
            return _Result(first=None)
        return _Result(first=None)

    def commit(self):
        self.commits += 1


class TeamMembersRouteTests(unittest.TestCase):
    def test_system_admin_lists_active_and_inactive_team_members(self):
        orm = _TeamOrm()
        with (
            patch.object(route, "current_user_id", return_value=orm.caller_id),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            members = route.list_team_members(request=object(), orm=orm)

        self.assertEqual(len(members), 2)
        self.assertTrue(members[0].is_active)
        self.assertFalse(members[1].is_active)
        self.assertEqual(members[0].project_count, 3)
        self.assertIn("COUNT(pm.project_id)", orm.sql[0])

    def test_non_system_admin_cannot_list_team_members(self):
        orm = _TeamOrm()
        with (
            patch.object(route, "current_user_id", return_value=orm.caller_id),
            patch.object(route, "is_system_admin", return_value=False),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.list_team_members(request=object(), orm=orm)

        self.assertEqual(raised.exception.status_code, 403)

    def test_system_admin_creates_team_member_without_project_membership(self):
        orm = _TeamOrm()
        with (
            patch.object(route, "current_user_id", return_value=orm.caller_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit") as audit,
        ):
            created = route.create_team_member(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                body=route.CreateTeamMemberRequest(
                    username="newmember",
                    nickname="新成员",
                    password="654321",
                ),
                orm=orm,
            )

        self.assertEqual(created.username, "newmember")
        joined_sql = "\n".join(orm.sql)
        self.assertIn("INSERT INTO auth.users", joined_sql)
        self.assertIn("INSERT INTO auth.identities", joined_sql)
        self.assertIn("INSERT INTO public.users", joined_sql)
        self.assertNotIn("INSERT INTO public.project_members", joined_sql)
        password_params = next(
            values for sql, values in zip(orm.sql, orm.params) if "INSERT INTO auth.users" in sql
        )
        self.assertEqual(password_params["password"], "654321")
        self.assertEqual(orm.commits, 1)
        self.assertEqual(audit.call_args.kwargs["action"], "create_team_member")

    def test_deactivate_team_member_revokes_projects_and_login_but_keeps_user(self):
        orm = _TeamOrm()
        with (
            patch.object(route, "current_user_id", return_value=orm.caller_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit") as audit,
        ):
            route.deactivate_team_member(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                user_id=orm.target_id,
                orm=orm,
            )

        joined_sql = "\n".join(orm.sql)
        self.assertIn("DELETE FROM public.project_members", joined_sql)
        self.assertIn("is_active = false", joined_sql)
        self.assertIn("banned_until", joined_sql)
        self.assertIn("DELETE FROM auth.sessions", joined_sql)
        self.assertNotIn("DELETE FROM auth.users", joined_sql)
        self.assertNotIn("DELETE FROM public.users", joined_sql)
        self.assertEqual(orm.commits, 1)
        self.assertEqual(audit.call_args.kwargs["action"], "deactivate_team_member")

    def test_deactivate_team_member_rejects_current_user(self):
        orm = _TeamOrm()
        with (
            patch.object(route, "current_user_id", return_value=orm.caller_id),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.deactivate_team_member(
                    request=object(),
                    user_id=orm.caller_id,
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 400)

    def test_reactivate_team_member_preserves_identity(self):
        orm = _TeamOrm(target_active=False)
        with (
            patch.object(route, "current_user_id", return_value=orm.caller_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit") as audit,
        ):
            restored = route.reactivate_team_member(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                user_id=orm.target_id,
                orm=orm,
            )

        self.assertEqual(restored.user_id, orm.target_id)
        joined_sql = "\n".join(orm.sql)
        self.assertIn("is_active = true", joined_sql)
        self.assertIn("banned_until = NULL", joined_sql)
        self.assertEqual(audit.call_args.kwargs["action"], "reactivate_team_member")

    def test_team_page_owns_username_and_password_changes(self):
        orm = _TeamOrm()
        with (
            patch.object(route, "current_user_id", return_value=orm.caller_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit") as audit,
        ):
            renamed = route.rename_team_member_username(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                user_id=orm.target_id,
                body=route.RenameTeamMemberUsernameRequest(username="renamed"),
                orm=orm,
            )
            reset = route.reset_team_member_password(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                user_id=orm.target_id,
                body=route.ResetTeamMemberPasswordRequest(password="7654321"),
                orm=orm,
            )

        self.assertEqual(renamed.username, "renamed")
        self.assertEqual(reset.status, "updated")
        joined_sql = "\n".join(orm.sql)
        self.assertIn("UPDATE auth.identities", joined_sql)
        self.assertIn("crypt(:password, gen_salt('bf'))", joined_sql)
        self.assertEqual(audit.call_count, 2)
        self.assertEqual(audit.call_args_list[0].kwargs["action"], "rename_team_member_username")
        self.assertEqual(audit.call_args_list[1].kwargs["action"], "reset_team_member_password")


if __name__ == "__main__":
    unittest.main()
