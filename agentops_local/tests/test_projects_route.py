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
    def __init__(
        self,
        *,
        caller_role: str | None = "developer",
        is_system_admin: bool = False,
    ) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.caller_role = caller_role
        self.is_system_admin = is_system_admin

    def execute(self, statement, params):
        sql = str(statement)
        self.sql.append(sql)
        self.params.append(params)
        if "SELECT COALESCE(is_system_admin" in sql:
            return _FirstResult(
                SimpleNamespace(is_system_admin=self.is_system_admin)
            )
        if "SELECT role::text AS role" in sql and "FROM public.project_members" in sql:
            return _FirstResult(
                SimpleNamespace(role=self.caller_role)
                if self.caller_role is not None
                else None
            )
        return _AllResult(
            [
                SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000011",
                    email="leader@local.dev",
                    username="leader",
                    nickname="研发负责人",
                    display_name="研发负责人",
                    role="owner",
                ),
                SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000012",
                    email="member@local.dev",
                    username="member",
                    nickname=None,
                    display_name="member@local.dev",
                    role="developer",
                ),
            ]
        )


class _MemberOptionsOrm:
    def __init__(self) -> None:
        self.sql = ""
        self.params = {}

    def execute(self, statement, params):
        self.sql = str(statement)
        self.params = params
        return _AllResult(
            [
                SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000013",
                    email="candidate@local.dev",
                    username="candidate",
                    nickname="候选成员",
                    display_name="候选成员",
                )
            ]
        )


class _AddMemberOrm:
    def __init__(self, *, existing_user: bool = True, existing_project_role: str | None = None, owner_count: int = 1) -> None:
        self.existing_user = existing_user
        self.existing_project_role = existing_project_role
        self.owner_count = owner_count
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
        if "SELECT role::text AS role" in sql and "FROM public.project_members" in sql:
            return _FirstResult(
                SimpleNamespace(role=self.existing_project_role)
                if self.existing_project_role is not None
                else None
            )
        if "COUNT(*) AS owner_count" in sql:
            return _FirstResult(SimpleNamespace(owner_count=self.owner_count))
        return _FirstResult(None)

    def commit(self):
        self.commits += 1


class _MembersAdminOrm:
    def __init__(self, *, department_exists: bool = True, target_role: str = "business_user", owner_count: int = 1) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.commits = 0
        self.department_exists = department_exists
        self.target_role = target_role
        self.owner_count = owner_count

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
                    department_id=params.get("department_id", "research"),
                    created_at="2026-07-28 08:00:00+00",
                    completed_at=params.get("completed_at"),
                )
            )
        if "FROM public.departments" in sql:
            return _FirstResult(
                SimpleNamespace(id=params["department_id"])
                if self.department_exists
                else None
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
                    role=self.target_role,
                )
            )
        if "COUNT(*) AS owner_count" in sql:
            return _FirstResult(SimpleNamespace(owner_count=self.owner_count))
        return _FirstResult(None)

    def commit(self):
        self.commits += 1


class _DepartmentMigrationOrm:
    migration_id = "00000000-0000-0000-0000-000000000060"

    def __init__(self, *, source_department_id="research-direct") -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.events: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.source_department_id = source_department_id
        self.job = None

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.sql.append(sql)
        self.params.append(values)
        self.events.append(sql)
        if "FROM public.departments" in sql:
            return _FirstResult(
                SimpleNamespace(id=values["department_id"], parent_id="education", allows_projects=True)
            )
        if (
            "FROM public.projects" in sql
            and "department_id" in sql
            and (
                "FOR UPDATE" in sql
                or "id::text AS id, department_id" in sql
            )
        ):
            return _FirstResult(
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000010",
                    org_id="00000000-0000-0000-0000-000000000020",
                    name="Migration Project",
                    environment="development",
                    department_id=self.source_department_id,
                    created_at="2026-08-12 09:00:00+00",
                    completed_at=None,
                )
            )
        if "SELECT COUNT(*)" in sql and "project_material_documents" in sql:
            return _FirstResult(SimpleNamespace(count=3))
        if "SELECT COUNT(*)" in sql and "project_wiki_pages" in sql:
            return _FirstResult(SimpleNamespace(count=5))
        if "SELECT COUNT(*)" in sql and "meeting_summaries" in sql:
            return _FirstResult(SimpleNamespace(count=2))
        if "INSERT INTO public.project_department_migrations" in sql:
            self.job = {
                "id": values["migration_id"],
                "project_id": values["project_id"],
                "source_department_id": values["source_department_id"],
                "target_department_id": values["target_department_id"],
                "status": "queued",
                "current_step": "queued",
                "progress": 0,
                "raw_material_count": values["raw_material_count"],
                "wiki_page_count": values["wiki_page_count"],
                "meeting_record_count": values["meeting_record_count"],
                "documents_updated": 0,
                "material_intakes_updated": 0,
                "memory_drafts_updated": 0,
                "pending_requests_updated": 0,
                "verified": False,
                "error_message": None,
            }
            return _FirstResult(None)
        if "FROM public.project_department_migrations" in sql:
            return _FirstResult(
                SimpleNamespace(
                    **self.job,
                    created_at="2026-08-12 09:00:00+00",
                    started_at=None,
                    completed_at=None,
                    updated_at="2026-08-12 09:00:00+00",
                )
                if self.job
                else None
            )
        return _FirstResult(None)

    def commit(self):
        self.commits += 1
        self.events.append("COMMIT")

    def rollback(self):
        self.rollbacks += 1


class _RenameMemberOrm:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.commits = 0

    def execute(self, statement, params):
        sql = str(statement)
        self.sql.append(sql)
        self.params.append(params)
        if "FROM public.project_members pm" in sql and "JOIN auth.users" in sql:
            return _FirstResult(
                SimpleNamespace(
                    user_id="00000000-0000-0000-0000-000000000012",
                    email="wuyichen@local.dev",
                    username="wuyichen",
                    nickname=None,
                    display_name="wuyichen",
                    role="business_user",
                )
            )
        if "SELECT id FROM auth.users" in sql:
            return _FirstResult(None)
        return _FirstResult(None)

    def commit(self):
        self.commits += 1


class _ProjectRequestOrm:
    def __init__(
        self,
        *,
        has_user_org_membership: bool = True,
        has_project_membership: bool = False,
        department_allows_projects: bool = True,
    ) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.commits = 0
        self.created_values: dict | None = None
        self.has_user_org_membership = has_user_org_membership
        self.has_project_membership = has_project_membership
        self.department_allows_projects = department_allows_projects

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.sql.append(sql)
        self.params.append(values)
        if "FROM public.project_members" in sql and self.has_project_membership:
            return _FirstResult(SimpleNamespace(allowed=True))
        if "FROM public.user_orgs" in sql:
            return _FirstResult(
                SimpleNamespace(role="business_user")
                if self.has_user_org_membership
                else None
            )
        if "FROM public.departments" in sql:
            return _FirstResult(
                SimpleNamespace(
                    id="research",
                    allows_projects=self.department_allows_projects,
                )
            )
        if "INSERT INTO public.project_creation_requests" in sql:
            self.created_values = values
            return _FirstResult(None)
        if "FROM public.project_creation_requests request_row" in sql and self.created_values:
            return _FirstResult(
                SimpleNamespace(
                    id=self.created_values["id"],
                    requester_id=self.created_values["requester_id"],
                    requester_username="member",
                    org_id=self.created_values["org_id"],
                    org_name="智慧大脑",
                    name=self.created_values["name"],
                    environment=self.created_values["environment"],
                    department_id=self.created_values["department_id"],
                    department_name="研发",
                    completed_at=self.created_values["completed_at"],
                    reason=self.created_values["reason"],
                    status="pending",
                    review_comment=None,
                    reviewed_by_user_id=None,
                    created_project_id=None,
                    created_at="2026-08-10 09:00:00+00",
                    reviewed_at=None,
                )
            )
        return _FirstResult(None)

    def commit(self):
        self.commits += 1


class _ProjectRequestReviewOrm:
    request_id = "00000000-0000-0000-0000-000000000030"
    requester_id = "00000000-0000-0000-0000-000000000001"
    org_id = "00000000-0000-0000-0000-000000000020"

    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[dict] = []
        self.commits = 0
        self.review_values: dict | None = None

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.sql.append(sql)
        self.params.append(values)
        if "FOR UPDATE" in sql and "project_creation_requests" in sql:
            return _FirstResult(
                SimpleNamespace(
                    id=self.request_id,
                    requester_id=self.requester_id,
                    requester_username="member",
                    org_id=self.org_id,
                    org_name="智慧大脑",
                    name="新材料平台",
                    environment="development",
                    department_id="research",
                    department_name="研发",
                    completed_at="2026-12-31",
                    reason="需要独立管理研发资料",
                    status="pending",
                    review_comment=None,
                    reviewed_by_user_id=None,
                    created_project_id=None,
                    created_at="2026-08-10 09:00:00+00",
                    reviewed_at=None,
                )
            )
        if "FROM public.departments" in sql:
            return _FirstResult(SimpleNamespace(id="research", allows_projects=True))
        if "FROM public.projects" in sql and "lower(name)" in sql:
            return _FirstResult(None)
        if "INSERT INTO public.projects" in sql:
            return _FirstResult(
                SimpleNamespace(
                    created_at="2026-08-10 10:00:00+00",
                    completed_at="2026-12-31",
                )
            )
        if "UPDATE public.project_creation_requests" in sql:
            self.review_values = values
            return _FirstResult(None)
        if "FROM public.project_creation_requests request_row" in sql and self.review_values:
            return _FirstResult(
                SimpleNamespace(
                    id=self.request_id,
                    requester_id=self.requester_id,
                    requester_username="member",
                    org_id=self.org_id,
                    org_name="智慧大脑",
                    name="新材料平台",
                    environment="development",
                    department_id="research",
                    department_name="研发",
                    completed_at="2026-12-31",
                    reason="需要独立管理研发资料",
                    status=self.review_values["status"],
                    review_comment=self.review_values["review_comment"],
                    reviewed_by_user_id=self.review_values["reviewer_id"],
                    created_project_id=self.review_values.get("created_project_id"),
                    created_at="2026-08-10 09:00:00+00",
                    reviewed_at="2026-08-10 10:00:00+00",
                )
            )
        return _FirstResult(None)

    def commit(self):
        self.commits += 1


class _ProjectRequestListOrm:
    def __init__(self) -> None:
        self.sql = ""
        self.params = {}

    def execute(self, statement, params=None):
        self.sql = str(statement)
        self.params = params or {}
        return _AllResult([])


class ProjectsRouteTests(unittest.TestCase):
    def test_project_catalog_includes_every_business_project_but_hides_unused_account_scaffolds(self) -> None:
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        orm = _Orm()

        with patch.object(route, "current_user_id", return_value=user_id):
            projects = route.list_project_catalog(request=object(), orm=orm)

        self.assertEqual([project.name for project in projects], ["Member Project"])
        self.assertIn("FROM public.projects p", orm.sql)
        self.assertIn("LEFT JOIN public.project_members pm", orm.sql)
        self.assertIn("pm.user_id = :u", orm.sql)
        self.assertIn("is_system_admin", orm.sql)
        self.assertIn("THEN 'owner'", orm.sql)
        self.assertIn("p.name <> 'Default Project'", orm.sql)
        self.assertIn("FROM public.project_members catalog_member", orm.sql)
        self.assertIn("catalog_member.project_id = p.id", orm.sql)
        self.assertNotIn("WHERE pm.user_id = :u", orm.sql)
        self.assertIn("CASE WHEN p.completed_at IS NULL THEN 0 ELSE 1 END", orm.sql)
        self.assertEqual(orm.params, {"u": str(user_id)})

    def test_create_project_accepts_dynamic_department_identifier(self) -> None:
        body = route.CreateProjectRequest(
            org_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
            name="质量平台",
            department_id="quality",
        )

        self.assertEqual(body.department_id, "quality")

    def test_ordinary_member_can_submit_project_creation_request(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        orm = _ProjectRequestOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "record_audit") as audit,
        ):
            created = route.create_project_request(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                body=route.CreateProjectRequestSubmission(
                    org_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
                    name="新材料平台",
                    department_id="research",
                    completed_at="2026-12-31",
                    reason="需要独立管理研发资料",
                ),
                orm=orm,
            )

        self.assertEqual(created.status, "pending")
        self.assertEqual(created.requester_username, "member")
        self.assertTrue(any("FROM public.user_orgs" in sql for sql in orm.sql))
        self.assertTrue(any("INSERT INTO public.project_creation_requests" in sql for sql in orm.sql))
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "request_project_creation")

    def test_project_member_can_request_in_project_organization_without_user_org_row(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        orm = _ProjectRequestOrm(
            has_user_org_membership=False,
            has_project_membership=True,
        )

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "record_audit"),
        ):
            created = route.create_project_request(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                body=route.CreateProjectRequestSubmission(
                    org_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
                    name="项目成员新申请",
                    department_id="research",
                    reason="当前组织内已有项目成员需要申请新项目",
                ),
                orm=orm,
            )

        self.assertEqual(created.status, "pending")
        access_sql = orm.sql[0]
        self.assertIn("FROM public.project_members", access_sql)
        self.assertIn("JOIN public.projects", access_sql)

    def test_project_request_rejects_non_project_hierarchy_group(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        orm = _ProjectRequestOrm(department_allows_projects=False)

        with patch.object(route, "current_user_id", return_value=caller_id):
            with self.assertRaises(route.HTTPException) as raised:
                route.create_project_request(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    body=route.CreateProjectRequestSubmission(
                        org_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
                        name="产业侧错误挂载",
                        department_id="industry",
                        reason="一级分组不能直接挂项目",
                    ),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("project category", raised.exception.detail)
        self.assertFalse(any("INSERT INTO public.project_creation_requests" in sql for sql in orm.sql))

    def test_project_request_listing_is_scoped_to_requester_unless_system_admin(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        member_orm = _ProjectRequestListOrm()
        admin_orm = _ProjectRequestListOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "is_system_admin", return_value=False),
        ):
            route.list_project_requests(request=object(), orm=member_orm)
        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            route.list_project_requests(request=object(), orm=admin_orm)

        self.assertIn("requester_id = :requester_id", member_orm.sql)
        self.assertNotIn("requester_id = :requester_id", admin_orm.sql)

    def test_system_admin_approval_creates_project_and_makes_requester_owner(self) -> None:
        reviewer_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        request_id = uuid.UUID(_ProjectRequestReviewOrm.request_id)
        orm = _ProjectRequestReviewOrm()

        with (
            patch.object(route, "current_user_id", return_value=reviewer_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit") as audit,
        ):
            reviewed = route.review_project_request(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                request_id=request_id,
                body=route.ReviewProjectRequest(decision="approve", comment="同意立项"),
                orm=orm,
            )

        self.assertEqual(reviewed.status, "approved")
        self.assertIsNotNone(reviewed.created_project_id)
        joined_sql = "\n".join(orm.sql)
        self.assertIn("INSERT INTO public.projects", joined_sql)
        self.assertIn("INSERT INTO public.project_members", joined_sql)
        owner_params = next(
            params for sql, params in zip(orm.sql, orm.params)
            if "INSERT INTO public.project_members" in sql
        )
        self.assertEqual(owner_params["user_id"], _ProjectRequestReviewOrm.requester_id)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "review_project_creation")

    def test_non_system_admin_cannot_review_project_request(self) -> None:
        reviewer_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        orm = _ProjectRequestReviewOrm()

        with (
            patch.object(route, "current_user_id", return_value=reviewer_id),
            patch.object(route, "is_system_admin", return_value=False),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.review_project_request(
                    request=object(),
                    request_id=uuid.UUID(_ProjectRequestReviewOrm.request_id),
                    body=route.ReviewProjectRequest(decision="reject", comment="信息不足"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 403)

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
        self.assertIn("CASE WHEN p.completed_at IS NULL THEN 0 ELSE 1 END", orm.sql)
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

    def test_update_project_clears_completed_at(self) -> None:
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
                body=route.UpdateProjectRequest(completed_at=None),
                orm=orm,
            )

        update_sql = next(sql for sql in orm.sql if "UPDATE public.projects" in sql)
        update_params = next(
            params for sql, params in zip(orm.sql, orm.params)
            if "UPDATE public.projects" in sql
        )
        self.assertIsNone(project.completed_at)
        self.assertIn("completed_at = CAST(:completed_at AS date)", update_sql)
        self.assertIsNone(update_params["completed_at"])
        audit.assert_called_once()
        self.assertIn("completed_at", audit.call_args.kwargs["metadata"]["updated_fields"])

    def test_update_project_transfers_to_another_department(self) -> None:
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
                body=route.UpdateProjectRequest(department_id="marketing"),
                orm=orm,
            )

        self.assertEqual(project.department_id, "marketing")
        update_sql = next(sql for sql in orm.sql if "UPDATE public.projects" in sql)
        update_params = next(
            params for sql, params in zip(orm.sql, orm.params)
            if "UPDATE public.projects" in sql
        )
        self.assertIn("department_id = :department_id", update_sql)
        self.assertEqual(update_params["department_id"], "marketing")
        audit.assert_called_once()
        self.assertIn("department_id", audit.call_args.kwargs["metadata"]["updated_fields"])

    def test_legacy_patch_transfer_synchronizes_redundant_department_snapshots(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit"),
        ):
            route.update_project(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                body=route.UpdateProjectRequest(department_id="marketing"),
                orm=orm,
            )

        joined = "\n".join(orm.sql)
        self.assertIn("UPDATE public.documents", joined)
        self.assertIn("UPDATE public.project_material_intakes", joined)
        self.assertIn("UPDATE public.project_memory_drafts", joined)
        self.assertIn("UPDATE public.project_creation_requests", joined)

    def test_start_department_migration_persists_inventory_and_dispatches_real_job(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _DepartmentMigrationOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(
                route.uuid,
                "uuid4",
                return_value=uuid.UUID(_DepartmentMigrationOrm.migration_id),
            ),
            patch.object(route, "_dispatch_department_migration") as dispatch,
        ):
            job = route.start_project_department_migration(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                body=route.CreateProjectDepartmentMigrationRequest(
                    target_department_id="education-direct",
                    expected_source_department_id="research-direct",
                    migrate_knowledge_base=True,
                    idempotency_key="profile-transfer-1",
                ),
                orm=orm,
            )

        self.assertEqual(job.status, "queued")
        self.assertEqual(job.raw_material_count, 3)
        self.assertEqual(job.wiki_page_count, 5)
        self.assertEqual(job.meeting_record_count, 2)
        insert_sql = next(
            sql for sql in orm.sql if "INSERT INTO public.project_department_migrations" in sql
        )
        self.assertIn("idempotency_key", insert_sql)
        dispatch.assert_called_once_with(uuid.UUID(_DepartmentMigrationOrm.migration_id))

    def test_start_department_migration_rejects_stale_expected_source(self) -> None:
        orm = _DepartmentMigrationOrm(source_department_id="science-direct")
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "require_admin", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.start_project_department_migration(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
                    body=route.CreateProjectDepartmentMigrationRequest(
                        target_department_id="education-direct",
                        expected_source_department_id="research-direct",
                    ),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(
            any("INSERT INTO public.project_department_migrations" in sql for sql in orm.sql)
        )

    def test_department_migration_worker_synchronizes_all_redundant_metadata(self) -> None:
        orm = _DepartmentMigrationOrm()
        orm.job = {
            "id": orm.migration_id,
            "project_id": "00000000-0000-0000-0000-000000000010",
            "source_department_id": "research-direct",
            "target_department_id": "education-direct",
            "status": "queued",
            "current_step": "queued",
            "progress": 0,
            "raw_material_count": 3,
            "wiki_page_count": 5,
            "meeting_record_count": 2,
            "documents_updated": 0,
            "material_intakes_updated": 0,
            "memory_drafts_updated": 0,
            "pending_requests_updated": 0,
            "verified": False,
            "error_message": None,
        }

        route._run_department_migration(orm, uuid.UUID(orm.migration_id))

        joined = "\n".join(orm.sql)
        self.assertIn("UPDATE public.projects", joined)
        self.assertIn("UPDATE public.documents", joined)
        self.assertIn("UPDATE public.project_material_intakes", joined)
        self.assertIn("UPDATE public.project_memory_drafts", joined)
        self.assertIn("UPDATE public.project_creation_requests", joined)
        self.assertIn("status = 'completed'", joined)
        self.assertIn("verified = true", joined)

    def test_department_migration_persists_running_status_before_core_transaction(self) -> None:
        orm = _DepartmentMigrationOrm()
        orm.job = {
            "id": orm.migration_id,
            "project_id": "00000000-0000-0000-0000-000000000010",
            "source_department_id": "research-direct",
            "target_department_id": "education-direct",
            "status": "queued",
            "current_step": "queued",
            "progress": 0,
            "raw_material_count": 3,
            "wiki_page_count": 5,
            "meeting_record_count": 2,
            "documents_updated": 0,
            "material_intakes_updated": 0,
            "memory_drafts_updated": 0,
            "pending_requests_updated": 0,
            "verified": False,
            "error_message": None,
        }

        route._run_department_migration(orm, uuid.UUID(orm.migration_id))

        commit_indexes = [
            index for index, event in enumerate(orm.events) if event == "COMMIT"
        ]
        project_update = next(
            index
            for index, event in enumerate(orm.events)
            if "UPDATE public.projects" in event
        )
        self.assertLess(commit_indexes[0], project_update)
        self.assertLess(commit_indexes[1], project_update)
        syncing_update = next(
            index
            for index, event in enumerate(orm.events)
            if "current_step = 'syncing_metadata'" in event
        )
        self.assertLess(syncing_update, commit_indexes[1])
        self.assertGreaterEqual(orm.commits, 3)

    def test_department_migration_background_failure_is_persisted_separately(self) -> None:
        primary_orm = _DepartmentMigrationOrm()
        recovery_orm = _DepartmentMigrationOrm()
        sessions = iter((primary_orm, recovery_orm))

        @contextmanager
        def fake_session_scope():
            orm = next(sessions)
            try:
                yield orm
                orm.commit()
            except Exception:
                orm.rollback()
                raise

        with (
            patch.object(route, "session_scope", fake_session_scope),
            patch.object(
                route,
                "_run_department_migration",
                side_effect=RuntimeError("core transaction failed"),
            ),
        ):
            route._run_department_migration_in_background(
                uuid.UUID(_DepartmentMigrationOrm.migration_id)
            )

        self.assertEqual(primary_orm.rollbacks, 1)
        self.assertEqual(recovery_orm.commits, 1)
        failed_update = next(
            sql
            for sql in recovery_orm.sql
            if "SET status = 'failed', current_step = 'failed'" in sql
        )
        self.assertIn("status <> 'completed'", failed_update)
        self.assertEqual(
            recovery_orm.params[-1]["error_message"],
            "core transaction failed",
        )

    def test_update_project_rejects_unknown_department(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm(department_exists=False)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.update_project(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    body=route.UpdateProjectRequest(department_id="missing"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertFalse(any("UPDATE public.projects" in sql for sql in orm.sql))

    def test_update_project_rejects_non_project_hierarchy_group(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        original_execute = orm.execute

        def execute(statement, params=None):
            sql = str(statement)
            if "FROM public.departments" in sql:
                orm.sql.append(sql)
                orm.params.append(params or {})
                return _FirstResult(SimpleNamespace(id="industry", allows_projects=False))
            return original_execute(statement, params)

        orm.execute = execute
        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.update_project(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    body=route.UpdateProjectRequest(department_id="industry"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("project category", raised.exception.detail)
        self.assertFalse(any("UPDATE public.projects" in sql for sql in orm.sql))

    def test_delete_project_removes_project_and_records_audit(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_owner", return_value=None) as require_owner,
            patch.object(route, "record_audit") as audit,
        ):
            route.delete_project(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                confirm_name="Member Project",
                orm=orm,
            )

        self.assertTrue(any("DELETE FROM public.projects" in sql for sql in orm.sql))
        require_owner.assert_called_once_with(orm, user_id=caller_id, project_id=project_id)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "delete_project")

    def test_delete_project_rejects_mismatched_confirmation_name(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_owner", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.delete_project(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    confirm_name="Wrong Project",
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("project name", raised.exception.detail)
        self.assertFalse(any("DELETE FROM public.projects" in sql for sql in orm.sql))

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
                body=route.AddMemberRequest(identifier="test1", role="developer"),
                orm=orm,
            )

        self.assertEqual(str(member.user_id), "00000000-0000-0000-0000-000000000012")
        self.assertEqual(member.email, "test1@local.dev")
        self.assertEqual(member.role, "developer")
        self.assertTrue(any("lower(au.email) = lower(:email)" in sql for sql in orm.sql))
        self.assertTrue(any("is_active" in sql for sql in orm.sql))
        auth_user_params = orm.params[0]
        self.assertEqual(auth_user_params, {"email": "test1@local.dev"})
        self.assertEqual(orm.commits, 1)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "add_member")

    def test_project_leader_cannot_assign_overall_lead_role(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _AddMemberOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "require_owner", side_effect=route.AuthzError(403, "need owner")),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.add_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    body=route.AddMemberRequest(identifier="test1", role="owner"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(any("INSERT INTO public.project_members" in sql for sql in orm.sql))

    def test_project_leader_cannot_downgrade_overall_lead(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _AddMemberOrm(existing_project_role="owner", owner_count=2)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "require_owner", side_effect=route.AuthzError(403, "need owner")),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.add_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    body=route.AddMemberRequest(identifier="test1", role="developer"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(any("INSERT INTO public.project_members" in sql for sql in orm.sql))

    def test_last_overall_lead_cannot_be_downgraded(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _AddMemberOrm(existing_project_role="owner", owner_count=1)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "require_owner", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.add_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    body=route.AddMemberRequest(identifier="test1", role="admin"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("at least one owner", raised.exception.detail)
        self.assertFalse(any("INSERT INTO public.project_members" in sql for sql in orm.sql))

    def test_project_member_role_rejects_legacy_business_user(self) -> None:
        with self.assertRaises(ValueError):
            route.AddMemberRequest(identifier="test1", role="business_user")

    def test_add_member_rejects_identifier_when_team_member_does_not_exist(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _AddMemberOrm(existing_user=False)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.add_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    body=route.AddMemberRequest(identifier="newdev", role="developer"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "active team member not found")
        joined_sql = "\n".join(orm.sql)
        self.assertNotIn("INSERT INTO auth.users", joined_sql)
        self.assertNotIn("INSERT INTO auth.identities", joined_sql)
        self.assertNotIn("INSERT INTO public.users", joined_sql)
        self.assertNotIn("INSERT INTO public.project_members", joined_sql)
        audit.assert_not_called()

    def test_add_member_query_excludes_agentops_system_accounts(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _AddMemberOrm(existing_user=False)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
        ):
            with self.assertRaises(route.HTTPException):
                route.add_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    body=route.AddMemberRequest(identifier="admin@agentops.local", role="developer"),
                    orm=orm,
                )

        self.assertIn("lower(au.email) NOT LIKE '%@agentops.local'", orm.sql[0])

    def test_authenticated_non_member_can_list_project_members_read_only(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersListOrm(caller_role=None)

        with patch.object(route, "current_user_id", return_value=caller_id):
            members = route.list_members(
                request=object(),
                project_id=project_id,
                orm=orm,
            )

        self.assertEqual([member.username for member in members], ["leader", "member"])
        self.assertTrue(any("JOIN auth.users" in sql for sql in orm.sql))
        self.assertFalse(any("SELECT role::text AS role" in sql for sql in orm.sql))

    def test_project_member_can_list_project_members(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersListOrm()

        with patch.object(route, "current_user_id", return_value=caller_id):
            members = route.list_members(
                request=object(),
                project_id=project_id,
                orm=orm,
            )

        self.assertEqual([member.email for member in members], ["leader@local.dev", "member@local.dev"])
        self.assertEqual([member.display_name for member in members], ["研发负责人", "member@local.dev"])
        self.assertEqual([member.role for member in members], ["owner", "developer"])
        self.assertEqual([member.username for member in members], ["leader", "member"])
        self.assertFalse(any("SELECT COALESCE(is_system_admin" in sql for sql in orm.sql))
        self.assertFalse(any("SELECT role::text AS role" in sql for sql in orm.sql))
        roster_sql = next(sql for sql in orm.sql if "JOIN auth.users" in sql)
        self.assertIn("FROM public.project_members pm", roster_sql)
        self.assertIn("LEFT JOIN public.users", roster_sql)
        self.assertIn("split_part(au.email, '@', 1) AS username", roster_sql)

    def test_system_admin_can_list_project_members_without_membership(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersListOrm(caller_role=None, is_system_admin=True)

        with patch.object(route, "current_user_id", return_value=caller_id):
            members = route.list_members(
                request=object(),
                project_id=project_id,
                orm=orm,
            )

        self.assertEqual([member.username for member in members], ["leader", "member"])
        self.assertFalse(any("SELECT COALESCE(is_system_admin" in sql for sql in orm.sql))
        self.assertFalse(any("SELECT role::text AS role" in sql for sql in orm.sql))

    def test_project_admin_can_list_active_team_members_not_yet_in_project(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MemberOptionsOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
        ):
            options = route.list_member_options(
                request=object(),
                project_id=project_id,
                orm=orm,
            )

        self.assertEqual(options[0].username, "candidate")
        self.assertIn("is_active", orm.sql)
        self.assertIn("NOT EXISTS", orm.sql)
        self.assertIn("NOT LIKE '%@agentops.local'", orm.sql)
        self.assertEqual(orm.params, {"project_id": str(project_id)})

    def test_admin_can_rename_local_member_username_without_changing_user_id(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        target_id = uuid.UUID("00000000-0000-0000-0000-000000000012")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _RenameMemberOrm()

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            member = route.rename_member_username(
                request=SimpleNamespace(state=SimpleNamespace(), client=None),
                project_id=project_id,
                user_id=target_id,
                body=route.RenameMemberUsernameRequest(username="wuyuchen"),
                orm=orm,
            )

        self.assertEqual(member.user_id, target_id)
        self.assertEqual(member.username, "wuyuchen")
        self.assertEqual(member.email, "wuyuchen@local.dev")
        joined_sql = "\n".join(orm.sql)
        self.assertIn("UPDATE auth.users", joined_sql)
        self.assertIn("UPDATE public.users", joined_sql)
        self.assertIn("UPDATE public.user_orgs", joined_sql)
        self.assertIn("UPDATE auth.identities", joined_sql)
        self.assertNotIn("UPDATE auth.identities\n            SET email", joined_sql)
        self.assertIn("DELETE FROM auth.sessions", joined_sql)
        self.assertEqual(orm.commits, 1)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.kwargs["action"], "rename_member_username")
        self.assertEqual(audit.call_args.kwargs["metadata"]["old_username"], "wuyichen")
        self.assertEqual(audit.call_args.kwargs["metadata"]["new_username"], "wuyuchen")

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

    def test_project_lead_cannot_remove_overall_lead(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        target_id = uuid.UUID("00000000-0000-0000-0000-000000000012")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm(target_role="owner", owner_count=2)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "require_owner", side_effect=route.AuthzError(403, "need owner")),
            patch.object(route, "record_audit") as audit,
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.remove_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    user_id=target_id,
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertFalse(any("DELETE FROM public.project_members" in sql for sql in orm.sql))
        audit.assert_not_called()

    def test_last_overall_lead_cannot_be_removed(self) -> None:
        caller_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        target_id = uuid.UUID("00000000-0000-0000-0000-000000000012")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = _MembersAdminOrm(target_role="owner", owner_count=1)

        with (
            patch.object(route, "current_user_id", return_value=caller_id),
            patch.object(route, "require_admin", return_value=None),
            patch.object(route, "require_owner", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.remove_member(
                    request=SimpleNamespace(state=SimpleNamespace(), client=None),
                    project_id=project_id,
                    user_id=target_id,
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("at least one owner", raised.exception.detail)
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
