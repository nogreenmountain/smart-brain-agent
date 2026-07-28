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
            "PROJECTS_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "projects.py",
        )
    )
    spec = importlib.util.spec_from_file_location(
        "projects_route_under_test",
        route_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class _Result:
    def all(self):
        return [
            SimpleNamespace(
                id="00000000-0000-0000-0000-000000000010",
                org_id="00000000-0000-0000-0000-000000000020",
                name="Member Project",
                environment="development",
                department_id="research",
                role="developer",
                created_at="2026-07-28 08:00:00+00",
                completed_at="2026-12-31",
            )
        ]


class _Orm:
    def __init__(self) -> None:
        self.sql = ""
        self.params = {}

    def execute(self, statement, params):
        self.sql = str(statement)
        self.params = params
        return _Result()


class _FirstResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _AllResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _MembersListOrm:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []

    def execute(self, statement, params):
        self.sql.append(str(statement))
        self.params.append(params)
        return _AllResult(
            [
                SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000011",
                    email="leader@local.dev",
                    role="owner",
                ),
                SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000012",
                    email="member@local.dev",
                    role="developer",
                ),
            ]
        )


class _AddMemberOrm:
    def __init__(self, *, existing_user: bool = True) -> None:
        self.existing_user = existing_user
        self.created_user_id = "00000000-0000-0000-0000-000000000099"
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.commits = 0

    def execute(self, statement, params):
        sql = str(statement)
        self.sql.append(sql)
        self.params.append(params)
        if "FROM auth.users" in sql:
            if not self.existing_user:
                return _FirstResult(None)
            return _FirstResult(
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000012",
                    email="test1@local.dev",
                )
            )
        if "INSERT INTO auth.users" in sql:
            return _FirstResult(
                SimpleNamespace(
                    id=self.created_user_id,
                    email=params["email"],
                )
            )
        return _FirstResult(None)

    def commit(self):
        self.commits += 1


class _MembersAdminOrm:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.commits = 0

    def execute(self, statement, params):
        sql = str(statement)
        self.sql.append(sql)
        self.params.append(params)
        if "UPDATE public.projects" in sql:
            return _FirstResult(
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000010",
                    org_id="00000000-0000-0000-0000-000000000020",
                    name=params.get("name", "Member Project"),
                    environment="development",
                    department_id="research",
                    created_at="2026-07-28 08:00:00+00",
                    completed_at=params.get("completed_at"),
                )
            )
        if "FROM public.projects" in sql:
            return _FirstResult(
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000010",
                    org_id="00000000-0000-0000-0000-000000000020",
                    name="Member Project",
                    environment="development",
                    department_id="research",
                    created_at="2026-07-28 08:00:00+00",
                    completed_at=None,
                )
            )
        if "FROM public.project_members pm" in sql and "JOIN auth.users" in sql:
            return _FirstResult(
                SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000012",
                    email="test1@local.dev",
                    role="business_user",
                )
            )
        return _FirstResult(None)

    def commit(self):
        self.commits += 1


class ProjectsRouteTests(unittest.TestCase):
    def test_list_projects_uses_direct_project_membership(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        orm = _Orm()

        with patch.object(route, "current_user_id", return_value=user_id):
            projects = route.list_projects(request=object(), orm=orm)

        self.assertEqual([project.name for project in projects], ["Member Project"])
        self.assertEqual(projects[0].role, "developer")
        self.assertEqual(projects[0].created_at, "2026-07-28 08:00:00+00")
        self.assertEqual(projects[0].completed_at, "2026-12-31")
        self.assertIn("project_members", orm.sql)
        self.assertIn("pm.role::text AS role", orm.sql)
        self.assertIn("p.created_at::text", orm.sql)
        self.assertIn("p.completed_at::text", orm.sql)
        self.assertIn("pm.user_id = :u", orm.sql)
        self.assertEqual(orm.params, {"u": str(user_id)})

    def test_update_project_renames_and_sets_completed_at(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            project = route.update_project(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                body=route.UpdateProjectRequest(name="新项目名", completed_at="2026-12-31"),
                orm=orm,
            )

        self.assertEqual(project.name, "新项目名")
        self.assertEqual(project.completed_at, "2026-12-31")
        update_sql = "\n".join(orm.sql)
        self.assertIn("UPDATE public.projects", update_sql)
        self.assertIn("completed_at", update_sql)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "update_project")

    def test_delete_project_removes_project_and_records_audit(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            route.delete_project(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                orm=orm,
            )

        self.assertTrue(any("DELETE FROM public.projects" in sql for sql in orm.sql))
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "delete_project")

    def test_add_member_accepts_short_username_identifier(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _AddMemberOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            member = route.add_member(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                body=route.AddMemberRequest(identifier="test1", role="business_user"),
                orm=orm,
            )

        self.assertEqual(str(member.user_id), "00000000-0000-0000-0000-000000000012")
        self.assertEqual(member.email, "test1@local.dev")
        self.assertEqual(member.role, "business_user")
        self.assertTrue(any("lower(email) = lower(:email)" in sql for sql in orm.sql))
        auth_user_params = orm.params[0]
        self.assertEqual(auth_user_params, {"email": "test1@local.dev"})
        self.assertEqual(orm.commits, 1)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "add_member")

    def test_add_member_creates_local_login_user_when_identifier_does_not_exist(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _AddMemberOrm(existing_user=False)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            member = route.add_member(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                body=route.AddMemberRequest(identifier="newdev", role="developer"),
                orm=orm,
            )

        self.assertEqual(member.email, "newdev@local.dev")
        self.assertEqual(member.role, "developer")
        joined_sql = "\n".join(orm.sql)
        self.assertIn("INSERT INTO auth.users", joined_sql)
        self.assertIn("crypt(CAST(:password AS text), gen_salt('bf'))", joined_sql)
        self.assertIn("INSERT INTO auth.identities", joined_sql)
        self.assertIn("INSERT INTO public.users", joined_sql)
        self.assertIn("INSERT INTO public.project_members", joined_sql)
        create_params = next(params for sql, params in zip(orm.sql, orm.params) if "INSERT INTO auth.users" in sql)
        self.assertEqual(create_params["email"], "newdev@local.dev")
        self.assertEqual(create_params["password"], "123456")
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "add_member")

    def test_list_members_allows_regular_project_member(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersListOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_member", return_value=None) as require_member,
            patch.object(route, "require_admin", side_effect=AssertionError("admin should not be required")),
        ):
            members = route.list_members(
                request=object(),
                project_id=project_id,
                orm=orm,
            )

        require_member.assert_called_once_with(orm, user_id=caller_id, project_id=project_id)
        self.assertEqual([member.email for member in members], ["leader@local.dev", "member@local.dev"])
        self.assertEqual([member.role for member in members], ["owner", "developer"])
        self.assertIn("FROM public.project_members pm", orm.sql[0])

    def test_remove_member_deletes_member_and_records_audit(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        target_id = uuid.UUID("00000000-0000-0000-0000-000000000012")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            route.remove_member(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                user_id=target_id,
                orm=orm,
            )

        self.assertTrue(any("DELETE FROM public.project_members" in sql for sql in orm.sql))
        self.assertEqual(orm.commits, 1)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "remove_member")
        self.assertEqual(audit.call_args.kwargs["metadata"]["target_user_id"], str(target_id))

    def test_remove_member_rejects_self_removal(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.remove_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    user_id=caller_id,
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(any("DELETE FROM public.project_members" in sql for sql in orm.sql))
        audit.assert_not_called()

    def test_reset_member_password_hashes_password_and_records_safe_audit(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        target_id = uuid.UUID("00000000-0000-0000-0000-000000000012")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            response = route.reset_member_password(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                user_id=target_id,
                body=route.ResetMemberPasswordRequest(password="654321"),
                orm=orm,
            )

        self.assertEqual(response.email, "test1@local.dev")
        password_sql = "\n".join(orm.sql)
        self.assertIn("crypt(:password, gen_salt('bf'))", password_sql)
        self.assertTrue(any(params.get("password") == "654321" for params in orm.params))
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "reset_member_password")
        self.assertNotIn("654321", str(audit.call_args.kwargs["metadata"]))


if __name__ == "__main__":
    unittest.main()
