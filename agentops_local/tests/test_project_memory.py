from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_module(name: str, default_relative: str):
    path = Path(
        os.environ.get(
            f"{name.upper()}_PATH",
            Path(__file__).parents[1] / default_relative,
        )
    )
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectMemoryTemplateTests(unittest.TestCase):
    def test_build_markdown_uses_fixed_long_term_memory_template(self) -> None:
        templates = _load_module("project_memory_templates", "project_memory/templates.py")

        markdown = templates.build_project_memory_markdown(
            department_id="research",
            department_name="研发",
            project_name="智慧大脑 Agent",
            repository={
                "git_url": "https://github.com/example/smartbrain.git",
                "git_branch": "main",
            },
            sources=[
                templates.SourceText(
                    filename="交接.md",
                    format="md",
                    text="项目启动命令是 npm run dev。\n关键接口是 /v4/knowledge/search。",
                )
            ],
        )

        self.assertTrue(markdown.startswith("# 项目长期记忆：智慧大脑 Agent"))
        for heading in [
            "## 1. 项目概览",
            "## 2. 代码仓库与启动方式",
            "## 3. 技术架构",
            "## 4. 关键业务流程",
            "## 5. 数据库与接口",
            "## 6. 重要决策与约定",
            "## 7. 常见问题与排查",
            "## 8. 新员工交接清单",
            "## 9. 原始资料索引",
            "## 10. 待补充问题",
        ]:
            self.assertIn(heading, markdown)
        self.assertIn("部门：研发", markdown)
        self.assertIn("https://github.com/example/smartbrain.git", markdown)
        self.assertIn("交接.md", markdown)
        self.assertIn("项目启动命令是 npm run dev", markdown)


class ProjectMemoryParserTests(unittest.TestCase):
    def test_extract_text_supports_xlsx_cells(self) -> None:
        parsers = _load_module("project_memory_parsers", "project_memory/parsers.py")

        workbook = io.BytesIO()
        with zipfile.ZipFile(workbook, "w") as archive:
            archive.writestr(
                "xl/sharedStrings.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <si><t>FORMAT_TEST_EXCEL_R55</t></si>
                  <si><r><t>Project </t></r><r><t>Budget</t></r></si>
                </sst>""",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                """<?xml version="1.0" encoding="UTF-8"?>
                <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
                  <sheetData>
                    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
                    <row r="2"><c r="A2"><v>42</v></c><c r="B2" t="inlineStr"><is><t>Approved</t></is></c></row>
                  </sheetData>
                </worksheet>""",
            )

        with tempfile.NamedTemporaryFile("wb", suffix=".xlsx", delete=False) as tmp:
            tmp.write(workbook.getvalue())
            path = tmp.name
        try:
            result = parsers.extract_text(Path(path))
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(result.format, "xlsx")
        self.assertIn("FORMAT_TEST_EXCEL_R55", result.text)
        self.assertIn("Project Budget", result.text)
        self.assertIn("42", result.text)
        self.assertIn("Approved", result.text)

    def test_extract_text_supports_html_and_strips_scripts(self) -> None:
        parsers = _load_module("project_memory_parsers", "project_memory/parsers.py")

        with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False) as tmp:
            tmp.write("<h1>研发项目</h1><script>secret()</script><p>启动方式：pnpm dev</p>")
            path = tmp.name
        try:
            result = parsers.extract_text(Path(path))
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(result.format, "html")
        self.assertIn("研发项目", result.text)
        self.assertIn("启动方式：pnpm dev", result.text)
        self.assertNotIn("secret()", result.text)

    def test_extract_text_supports_code_files_as_project_materials(self) -> None:
        parsers = _load_module("project_memory_parsers", "project_memory/parsers.py")

        with tempfile.NamedTemporaryFile("w", suffix=".tsx", encoding="utf-8", delete=False) as tmp:
            tmp.write("export function Boot() { return <main>智慧大脑</main>; }\n")
            path = tmp.name
        try:
            result = parsers.extract_text(Path(path))
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(result.format, "tsx")
        self.assertIn("export function Boot", result.text)


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _Orm:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.params: list[dict] = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append(sql)
        self.params.append(params or {})
        if "FROM public.project_memory_drafts" in sql and "FOR UPDATE" in sql:
            return _Result(
                SimpleNamespace(
                    id=str(uuid.UUID("00000000-0000-0000-0000-000000000020")),
                    project_id=str(uuid.UUID("00000000-0000-0000-0000-000000000010")),
                    department_id="research",
                    status="pending_review",
                    markdown_content="# 项目长期记忆：测试项目\n\n## 1. 项目概览\n内容",
                    title="测试项目长期记忆",
                )
            )
        if "SELECT name, department_id FROM public.projects" in sql:
            return _Result(SimpleNamespace(name="测试项目", department_id="research-direct"))
        return _Result()

    def commit(self):
        self.commits += 1


class _DepartmentOrm:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.params: list[dict] = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append(sql)
        self.params.append(params or {})
        if "SELECT id, name, sort_order" in sql:
            return _Result(
                rows=[
                    SimpleNamespace(id="research", name="研发", sort_order=1),
                    SimpleNamespace(id="quality", name="质量", sort_order=4),
                ]
            )
        if "INSERT INTO public.departments" in sql:
            return _Result(
                row=SimpleNamespace(
                    id=params["department_id"],
                    name=params["name"],
                    sort_order=4,
                    parent_id=params.get("parent_id"),
                    parent_name=params.get("parent_name"),
                    allows_projects=bool(params.get("parent_id")),
                    level=2 if params.get("parent_id") else 1,
                )
            )
        return _Result()

    def commit(self):
        self.commits += 1


class _HierarchyDepartmentOrm:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.params: list[dict] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append(sql)
        self.params.append(params or {})
        return _Result(
            rows=[
                SimpleNamespace(
                    id="research",
                    name="研发支撑",
                    sort_order=1,
                    parent_id=None,
                    parent_name=None,
                    allows_projects=True,
                    level=1,
                ),
                SimpleNamespace(
                    id="industry",
                    name="产业侧",
                    sort_order=3,
                    parent_id=None,
                    parent_name=None,
                    allows_projects=False,
                    level=1,
                ),
                SimpleNamespace(
                    id="marketing",
                    name="市场",
                    sort_order=4,
                    parent_id="industry",
                    parent_name="产业侧",
                    allows_projects=True,
                    level=2,
                ),
            ]
        )


class ProjectMemoryRouteTests(unittest.TestCase):
    def test_only_hanshangbo_has_global_project_review_scope(self) -> None:
        route = _load_module("project_memory_global_reviewer_route", "api/routes/v4/project_memory.py")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        class ReviewerOrm:
            def __init__(self, email: str):
                self.email = email

            def execute(self, statement, params=None):
                return _Result(SimpleNamespace(email=self.email))

        self.assertTrue(route._is_global_project_reviewer(ReviewerOrm("hanshangbo@local.dev"), user_id))
        self.assertTrue(route._is_global_project_reviewer(ReviewerOrm("HANSHANGBO@LOCAL.DEV"), user_id))
        self.assertFalse(route._is_global_project_reviewer(ReviewerOrm("sysadmin@local.dev"), user_id))

    def test_project_leader_can_review_only_their_project(self) -> None:
        route = _load_module("project_memory_project_reviewer_route", "api/routes/v4/project_memory.py")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")

        class ReviewerOrm:
            def __init__(self, role: str):
                self.role = role

            def execute(self, statement, params=None):
                sql = str(statement)
                if "FROM auth.users" in sql:
                    return _Result(SimpleNamespace(email="project-leader@local.dev"))
                if "FROM public.project_members" in sql:
                    return _Result(SimpleNamespace(role=self.role))
                return _Result()

        route._require_project_reviewer(
            ReviewerOrm("admin"), user_id=user_id, project_id=project_id,
        )
        with self.assertRaises(route.HTTPException) as raised:
            route._require_project_reviewer(
                ReviewerOrm("developer"), user_id=user_id, project_id=project_id,
            )
        self.assertEqual(raised.exception.status_code, 403)

    def test_review_queue_returns_all_authorized_projects_with_project_attribution(self) -> None:
        route = _load_module("project_memory_review_queue_route", "api/routes/v4/project_memory.py")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        class QueueOrm:
            def __init__(self):
                self.executed = []
                self.params = []

            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                return _Result(rows=[
                    SimpleNamespace(
                        id="00000000-0000-0000-0000-000000000020",
                        project_id="00000000-0000-0000-0000-000000000010",
                        project_name="智慧大脑",
                        department_id="research-direct",
                        department_name="直属分级",
                        department_path="研发支撑 / 直属分级",
                        title="智慧大脑 原始项目资料审批",
                        status="pending_review",
                        markdown_content="# 待审批",
                        source_count=2,
                        uploader_user_id="00000000-0000-0000-0000-000000000002",
                        uploader_username="member",
                        uploader_nickname="普通成员",
                        uploader_display_name="普通成员",
                        file_names=["需求.docx", "方案.pptx"],
                        total_size_bytes=4096,
                        created_at="2026-08-18 09:00:00+00",
                        updated_at="2026-08-18 09:00:00+00",
                    )
                ])

        orm = QueueOrm()
        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_is_global_project_reviewer", return_value=False),
        ):
            rows = route.list_project_memory_review_queue(
                request=SimpleNamespace(state=SimpleNamespace()),
                orm=orm,
            )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].project_name, "智慧大脑")
        self.assertEqual(rows[0].department_path, "研发支撑 / 直属分级")
        self.assertEqual(rows[0].uploader.display_name, "普通成员")
        self.assertEqual(rows[0].file_names, ["需求.docx", "方案.pptx"])
        self.assertEqual(rows[0].total_size_bytes, 4096)
        sql = "\n".join(orm.executed)
        self.assertIn("pm.role::text IN ('owner', 'admin')", sql)
        self.assertIn("draft.status = 'pending_review'", sql)
        self.assertEqual(orm.params[-1]["user_id"], str(user_id))
        self.assertFalse(orm.params[-1]["global_reviewer"])

    def test_review_queue_identifies_meeting_and_repository_submissions(self) -> None:
        route = _load_module("project_memory_submission_queue_route", "api/routes/v4/project_memory.py")

        class QueueOrm:
            def execute(self, statement, params=None):
                return _Result(rows=[SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000020",
                    project_id="00000000-0000-0000-0000-000000000010",
                    project_name="智慧大脑", department_id="research-direct",
                    department_name="直属分级", department_path="研发 / 直属分级",
                    title="周会审批", status="pending_review", markdown_content="# 周会",
                    source_count=1, review_kind="meeting_summary",
                    submission_payload={"meeting_date": "2026-08-18"},
                    uploader_user_id=None, uploader_username=None, uploader_nickname=None,
                    uploader_display_name="成员", file_names=["周会.docx"], total_size_bytes=1024,
                    created_at="2026-08-18", updated_at="2026-08-18",
                )])

        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "_is_global_project_reviewer", return_value=True),
        ):
            rows = route.list_project_memory_review_queue(
                request=SimpleNamespace(state=SimpleNamespace()), orm=QueueOrm(),
            )

        self.assertEqual(rows[0].review_kind, "meeting_summary")
        self.assertEqual(rows[0].meeting_date, "2026-08-18")
        self.assertEqual(rows[0].file_names, ["周会.docx"])

    def test_departments_can_include_hierarchy_groups(self) -> None:
        route = _load_module("project_memory_hierarchy_route", "api/routes/v4/project_memory.py")
        orm = _HierarchyDepartmentOrm()

        rows = route.list_project_memory_departments(include_groups=True, orm=orm)

        self.assertEqual([row.id for row in rows], ["research", "industry", "marketing"])
        self.assertIsNone(rows[0].parent_id)
        self.assertFalse(rows[1].allows_projects)
        self.assertEqual(rows[2].parent_id, "industry")
        self.assertEqual(rows[2].parent_name, "产业侧")
        self.assertEqual(rows[2].level, 2)
        self.assertEqual(orm.params[-1], {"include_groups": True})

    def test_departments_are_loaded_from_database(self) -> None:
        route = _load_module("project_memory_departments_route", "api/routes/v4/project_memory.py")
        orm = _DepartmentOrm()

        rows = route.list_project_memory_departments(orm=orm)

        self.assertEqual([row.id for row in rows], ["research", "quality"])
        self.assertTrue(any("FROM public.departments" in sql for sql in orm.executed))

    def test_system_admin_can_create_department(self) -> None:
        route = _load_module("project_memory_create_department_route", "api/routes/v4/project_memory.py")
        orm = _DepartmentOrm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit", return_value=None),
        ):
            row = route.create_project_memory_department(
                request=SimpleNamespace(state=SimpleNamespace()),
                body=route.CreateDepartmentRequest(id="quality", name="质量", parent_id=None),
                orm=orm,
            )

        self.assertEqual(row.id, "quality")
        self.assertEqual(row.name, "质量")
        self.assertEqual(orm.commits, 1)
        self.assertTrue(any("INSERT INTO public.departments" in sql for sql in orm.executed))
        insert_params = next(
            params for sql, params in zip(orm.executed, orm.params)
            if "INSERT INTO public.departments" in sql
        )
        self.assertIsNone(insert_params["parent_id"])
        self.assertFalse(row.allows_projects)
        direct_insert_params = next(
            params
            for sql, params in zip(orm.executed, orm.params)
            if "INSERT INTO public.departments" in sql
            and params.get("parent_id") == "quality"
        )
        self.assertEqual(direct_insert_params["name"], "直属分级")
        self.assertTrue(direct_insert_params["allows_projects"])
        self.assertTrue(direct_insert_params["is_direct"])

    def test_system_admin_can_create_second_level_department_under_root(self) -> None:
        route = _load_module("project_memory_create_child_department_route", "api/routes/v4/project_memory.py")

        class _ChildDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "WHERE id = :parent_id" in sql:
                    return _Result(row=SimpleNamespace(id="industry", parent_id=None, name="产业侧"))
                if "INSERT INTO public.departments" in sql:
                    return _Result(row=SimpleNamespace(
                        id=params["department_id"], name=params["name"], sort_order=1,
                        parent_id=params["parent_id"], parent_name="产业侧",
                        allows_projects=True, level=2,
                    ))
                return _Result()

        orm = _ChildDepartmentOrm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit", return_value=None),
        ):
            row = route.create_project_memory_department(
                request=SimpleNamespace(state=SimpleNamespace()),
                body=route.CreateDepartmentRequest(id="industry-quality", name="质量", parent_id="industry"),
                orm=orm,
            )

        self.assertEqual(row.parent_id, "industry")
        self.assertTrue(row.allows_projects)
        insert_sql = next(sql for sql in orm.executed if "INSERT INTO public.departments" in sql)
        self.assertIn("parent_id", insert_sql)
        self.assertIn("allows_projects", insert_sql)

    def test_cannot_create_third_level_department(self) -> None:
        route = _load_module("project_memory_reject_third_level_route", "api/routes/v4/project_memory.py")

        class _NestedDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "WHERE id = :parent_id" in sql:
                    return _Result(row=SimpleNamespace(id="marketing", parent_id="industry", name="市场"))
                return _Result()

        orm = _NestedDepartmentOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.create_project_memory_department(
                    request=SimpleNamespace(state=SimpleNamespace()),
                    body=route.CreateDepartmentRequest(name="三级分类", parent_id="marketing"),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("second-level", raised.exception.detail)

    def test_system_admin_can_rename_and_reorder_department(self) -> None:
        route = _load_module("project_memory_update_department_route", "api/routes/v4/project_memory.py")

        class _UpdateDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "SELECT id, parent_id" in sql:
                    return _Result(row=SimpleNamespace(id="industry", parent_id=None))
                if "UPDATE public.departments" in sql:
                    return _Result(row=SimpleNamespace(
                        id="industry", name=params["name"], sort_order=params["sort_order"],
                        parent_id=None, parent_name=None, allows_projects=False, level=1,
                    ))
                return _Result()

        orm = _UpdateDepartmentOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit", return_value=None),
        ):
            row = route.update_project_memory_department(
                request=SimpleNamespace(state=SimpleNamespace()),
                department_id="industry",
                body=route.UpdateDepartmentRequest(name="产业项目", sort_order=15),
                orm=orm,
            )

        self.assertEqual(row.name, "产业项目")
        self.assertEqual(row.sort_order, 15)

    def test_system_admin_can_move_second_level_department_to_another_root(self) -> None:
        route = _load_module("project_memory_move_department_route", "api/routes/v4/project_memory.py")

        class _MoveDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "SELECT id, parent_id" in sql and "department_id" in (params or {}):
                    return _Result(row=SimpleNamespace(id="marketing", parent_id="industry"))
                if "SELECT id, name, parent_id" in sql and "parent_id" in (params or {}):
                    return _Result(row=SimpleNamespace(id="education", name="教学侧", parent_id=None))
                if "UPDATE public.departments" in sql:
                    return _Result(row=SimpleNamespace(
                        id="marketing", name=params["name"], sort_order=params["sort_order"],
                        parent_id="education", parent_name="教学侧", allows_projects=True, level=2,
                    ))
                return _Result()

        orm = _MoveDepartmentOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit", return_value=None),
        ):
            row = route.update_project_memory_department(
                request=SimpleNamespace(state=SimpleNamespace()),
                department_id="marketing",
                body=route.UpdateDepartmentRequest(name="市场", sort_order=9, parent_id="education"),
                orm=orm,
            )

        self.assertEqual(row.parent_id, "education")
        update_sql = next(sql for sql in orm.executed if "UPDATE public.departments" in sql)
        self.assertIn("parent_id = :parent_id", update_sql)

    def test_direct_department_cannot_be_renamed_or_moved(self) -> None:
        route = _load_module("project_memory_protect_direct_update_route", "api/routes/v4/project_memory.py")

        class _DirectDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "SELECT id, parent_id" in sql:
                    return _Result(row=SimpleNamespace(
                        id="research-direct", parent_id="research", is_direct=True,
                    ))
                return _Result()

        orm = _DirectDepartmentOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.update_project_memory_department(
                    request=SimpleNamespace(state=SimpleNamespace()),
                    department_id="research-direct",
                    body=route.UpdateDepartmentRequest(
                        name="改名", sort_order=99, parent_id="education",
                    ),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("direct category", raised.exception.detail)
        self.assertFalse(any("UPDATE public.departments" in sql for sql in orm.executed))

    def test_direct_department_cannot_be_deleted(self) -> None:
        route = _load_module("project_memory_protect_direct_delete_route", "api/routes/v4/project_memory.py")

        class _DirectDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "child_count" in sql and "project_count" in sql:
                    return _Result(row=SimpleNamespace(
                        is_direct=True, parent_id="research", custom_child_count=0,
                        direct_child_count=0, direct_project_count=0,
                        direct_request_count=0, project_count=0,
                        request_count=0,
                    ))
                return _Result()

        orm = _DirectDepartmentOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.delete_project_memory_department(
                    request=SimpleNamespace(state=SimpleNamespace()),
                    department_id="research-direct",
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("direct category", raised.exception.detail)
        self.assertFalse(any("DELETE FROM public.departments" in sql for sql in orm.executed))

    def test_department_delete_is_blocked_when_it_has_children_projects_or_pending_requests(self) -> None:
        route = _load_module("project_memory_delete_occupied_department_route", "api/routes/v4/project_memory.py")

        class _OccupiedDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "child_count" in sql and "project_count" in sql:
                    return _Result(row=SimpleNamespace(
                        is_direct=False, parent_id=None, custom_child_count=1,
                        direct_child_count=1, direct_project_count=2,
                        direct_request_count=1, project_count=2,
                        request_count=3,
                    ))
                return _Result()

        orm = _OccupiedDepartmentOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.delete_project_memory_department(
                    request=SimpleNamespace(state=SimpleNamespace()),
                    department_id="industry",
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("child categories", raised.exception.detail)
        self.assertFalse(any("DELETE FROM public.departments" in sql for sql in orm.executed))

    def test_department_delete_is_blocked_when_it_has_historical_project_requests(self) -> None:
        route = _load_module(
            "project_memory_delete_historical_request_route",
            "api/routes/v4/project_memory.py",
        )

        class _HistoricalRequestOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "custom_child_count" in sql:
                    return _Result(row=SimpleNamespace(
                        is_direct=False,
                        parent_id="industry",
                        custom_child_count=0,
                        direct_child_count=0,
                        direct_project_count=0,
                        direct_request_count=0,
                        project_count=0,
                        request_count=1,
                    ))
                return _Result()

        orm = _HistoricalRequestOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.delete_project_memory_department(
                    request=SimpleNamespace(state=SimpleNamespace()),
                    department_id="education-market",
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("project requests", raised.exception.detail)
        self.assertFalse(any("DELETE FROM public.departments" in sql for sql in orm.executed))

    def test_system_admin_can_delete_empty_department(self) -> None:
        route = _load_module("project_memory_delete_empty_department_route", "api/routes/v4/project_memory.py")

        class _EmptyDepartmentOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "child_count" in sql and "project_count" in sql:
                    return _Result(row=SimpleNamespace(
                        is_direct=False, parent_id="industry", custom_child_count=0,
                        direct_child_count=0, direct_project_count=0,
                        direct_request_count=0, project_count=0,
                        request_count=0,
                    ))
                if "DELETE FROM public.departments" in sql:
                    return _Result(row=SimpleNamespace(id="empty", name="空分类"))
                return _Result()

        orm = _EmptyDepartmentOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit", return_value=None),
        ):
            route.delete_project_memory_department(
                request=SimpleNamespace(state=SimpleNamespace()),
                department_id="empty",
                orm=orm,
            )

        self.assertEqual(orm.commits, 1)
        self.assertTrue(any("DELETE FROM public.departments" in sql for sql in orm.executed))

    def test_system_admin_can_delete_empty_root_with_only_its_direct_child(self) -> None:
        route = _load_module("project_memory_delete_empty_root_route", "api/routes/v4/project_memory.py")

        class _EmptyRootOrm(_DepartmentOrm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "custom_child_count" in sql:
                    return _Result(row=SimpleNamespace(
                        is_direct=False,
                        parent_id=None,
                        custom_child_count=0,
                        direct_child_count=1,
                        direct_project_count=0,
                        direct_request_count=0,
                        project_count=0,
                        request_count=0,
                    ))
                if "DELETE FROM public.departments" in sql:
                    return _Result(row=SimpleNamespace(id="quality", name="璐ㄩ噺"))
                return _Result()

        orm = _EmptyRootOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit", return_value=None),
        ):
            route.delete_project_memory_department(
                request=SimpleNamespace(state=SimpleNamespace()),
                department_id="quality",
                orm=orm,
            )

        self.assertEqual(
            sum("DELETE FROM public.departments" in sql for sql in orm.executed),
            1,
        )
        self.assertEqual(orm.commits, 1)

    def test_system_admin_can_create_department_without_entering_internal_id(self) -> None:
        route = _load_module("project_memory_auto_department_id_route", "api/routes/v4/project_memory.py")
        orm = _DepartmentOrm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "is_system_admin", return_value=True),
            patch.object(route, "record_audit", return_value=None),
            patch.object(
                route.uuid,
                "uuid4",
                return_value=uuid.UUID("12345678-90ab-cdef-1234-567890abcdef"),
            ),
        ):
            row = route.create_project_memory_department(
                request=SimpleNamespace(state=SimpleNamespace()),
                body=route.CreateDepartmentRequest(name="质量管理"),
                orm=orm,
            )

        self.assertEqual(row.id, "dept-1234567890abcdef1234567890abcdef")
        self.assertEqual(row.name, "质量管理")
        insert_params = next(
            params
            for sql, params in zip(orm.executed, orm.params)
            if "INSERT INTO public.departments" in sql
        )
        insert_sql = next(sql for sql in orm.executed if "INSERT INTO public.departments" in sql)
        self.assertEqual(insert_params["department_id"], "dept-1234567890abcdef1234567890abcdef")
        self.assertNotIn("created_by_user_id", insert_sql)

    def test_repository_change_is_submitted_for_review_without_replacing_active_repository(self) -> None:
        route = _load_module("project_memory_route", "api/routes/v4/project_memory.py")
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None) as require_member,
            patch.object(route, "require_writer", side_effect=AssertionError("writer should not be required")),
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.upsert_project_repository(
                request=SimpleNamespace(state=SimpleNamespace()),
                project_id=project_id,
                body=route.ProjectRepositoryRequest(
                    git_url="https://github.com/example/repo.git",
                    git_branch="main",
                ),
                orm=orm,
            )

        require_member.assert_called_once()
        self.assertEqual(response.git_url, "https://github.com/example/repo.git")
        self.assertEqual(response.status, "pending_review")
        self.assertFalse(any("INSERT INTO public.project_repositories" in sql for sql in orm.executed))
        self.assertTrue(any("INSERT INTO public.project_memory_submissions" in sql for sql in orm.executed))
        self.assertTrue(any("INSERT INTO public.project_memory_drafts" in sql for sql in orm.executed))

    def test_approve_draft_ingests_markdown_and_marks_approved(self) -> None:
        route = _load_module("project_memory_route", "api/routes/v4/project_memory.py")
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        draft_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        document_id = uuid.UUID("00000000-0000-0000-0000-000000000030")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_require_project_reviewer", return_value=None),
            patch.object(
                route,
                "ingest_markdown_memory",
                return_value=SimpleNamespace(
                    document_id=document_id,
                    chunk_count=3,
                    status="ready",
                    error=None,
                ),
            ) as ingest,
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.approve_project_memory_draft(
                request=SimpleNamespace(state=SimpleNamespace()),
                draft_id=draft_id,
                body=route.ReviewDraftRequest(decision="approve", comment="通过"),
                orm=orm,
            )

        self.assertEqual(response.status, "approved")
        self.assertEqual(response.document_id, document_id)
        ingest.assert_called_once()
        self.assertTrue(any("status = 'approved'" in sql for sql in orm.executed))
        self.assertGreaterEqual(orm.commits, 1)

    def test_repeated_approve_returns_existing_result_without_duplicate_ingest(self) -> None:
        route = _load_module("project_memory_idempotent_review_route", "api/routes/v4/project_memory.py")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        draft_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        document_id = uuid.UUID("00000000-0000-0000-0000-000000000030")

        class ApprovedOrm(_Orm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "FROM public.project_memory_drafts" in sql and "FOR UPDATE" in sql:
                    return _Result(SimpleNamespace(
                        id=str(draft_id),
                        project_id="00000000-0000-0000-0000-000000000010",
                        department_id="research-direct",
                        status="approved",
                        markdown_content="# 已入库",
                        title="已审批资料",
                        template_version="project-material-original-v1",
                        intake_id=None,
                        skill_candidates=[],
                        created_by_user_id=str(user_id),
                        submission_id=None,
                        submission_type=None,
                        approved_document_id=str(document_id),
                        approved_resource_id=None,
                    ))
                return _Result()

        orm = ApprovedOrm()
        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_require_project_reviewer", return_value=None),
            patch.object(route, "ingest_markdown_memory") as ingest,
            patch.object(route, "ingest_file") as ingest_file,
            patch.object(route, "record_audit") as audit,
        ):
            response = route.approve_project_memory_draft(
                request=SimpleNamespace(state=SimpleNamespace()),
                draft_id=draft_id,
                body=route.ReviewDraftRequest(decision="approve"),
                orm=orm,
            )

        self.assertEqual(response.status, "approved")
        self.assertEqual(response.document_id, document_id)
        ingest.assert_not_called()
        ingest_file.assert_not_called()
        audit.assert_not_called()
        self.assertFalse(any("INSERT INTO public.project_memory_reviews" in sql for sql in orm.executed))

    def test_repeated_repository_approve_refreshes_resource_after_waiting_for_draft_lock(self) -> None:
        route = _load_module(
            "project_memory_repository_idempotent_review_route",
            "api/routes/v4/project_memory.py",
        )
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        draft_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        submission_id = uuid.UUID("00000000-0000-0000-0000-000000000030")

        class StaleJoinOrm(_Orm):
            def execute(self, statement, params=None):
                sql = str(statement)
                self.executed.append(sql)
                self.params.append(params or {})
                if "FROM public.project_memory_drafts draft" in sql and "FOR UPDATE" in sql:
                    return _Result(SimpleNamespace(
                        id=str(draft_id),
                        project_id=str(project_id),
                        department_id="research-direct",
                        status="approved",
                        markdown_content="# 已入库仓库",
                        title="已审批仓库",
                        template_version="project-repository-submission-v1",
                        intake_id=None,
                        skill_candidates=[],
                        created_by_user_id=str(user_id),
                        submission_id=str(submission_id),
                        submission_type="project_repository",
                        approved_document_id=None,
                        approved_resource_id=None,
                    ))
                if "SELECT approved_resource_id::text" in sql:
                    return _Result(SimpleNamespace(approved_resource_id=str(project_id)))
                return _Result()

        orm = StaleJoinOrm()
        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_require_project_reviewer", return_value=None),
            patch.object(route, "record_audit") as audit,
        ):
            response = route.approve_project_memory_draft(
                request=SimpleNamespace(state=SimpleNamespace()),
                draft_id=draft_id,
                body=route.ReviewDraftRequest(decision="approve"),
                orm=orm,
            )

        self.assertEqual(response.status, "approved")
        self.assertEqual(response.resource_id, project_id)
        self.assertTrue(any("SELECT approved_resource_id::text" in sql for sql in orm.executed))
        audit.assert_not_called()
        self.assertFalse(any("INSERT INTO public.project_memory_reviews" in sql for sql in orm.executed))

    def test_approve_material_intake_ingests_original_files_only_after_review(self) -> None:
        route = _load_module("project_memory_route_v2", "api/routes/v4/project_memory.py")
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        draft_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        raw_document_id = uuid.UUID("00000000-0000-0000-0000-000000000030")
        storage_key = "00000000-0000-0000-0000-000000000010/00000000-0000-0000-0000-000000000040/00000000-0000-0000-0000-000000000041.md"

        def execute(statement, params=None):
            sql = str(statement)
            orm.executed.append(sql)
            orm.params.append(params or {})
            if "FROM public.project_memory_drafts" in sql and "FOR UPDATE" in sql:
                return _Result(
                    SimpleNamespace(
                        id=str(draft_id),
                        project_id="00000000-0000-0000-0000-000000000010",
                        department_id="research",
                        status="pending_review",
                        markdown_content="# 原始资料审批",
                        title="原始项目资料审批",
                        template_version="project-material-original-v1",
                        intake_id="00000000-0000-0000-0000-000000000040",
                        skill_candidates=[],
                        created_by_user_id=str(user_id),
                    )
                )
            if "FROM public.project_material_intake_files" in sql:
                return _Result(
                    rows=[
                        SimpleNamespace(
                            id="00000000-0000-0000-0000-000000000041",
                            filename="README.md",
                            format="md",
                            size_bytes=32,
                            content_hash="hash-1",
                            raw_content=b"",
                            storage_key=storage_key,
                            recommendation="keep",
                            included=True,
                        )
                    ]
                )
            return _Result()

        orm.execute = execute
        with tempfile.TemporaryDirectory() as temp_dir:
            stored_path = Path(temp_dir) / storage_key
            stored_path.parent.mkdir(parents=True, exist_ok=True)
            stored_path.write_bytes(b"# Project\n\nRun Docker")
            with (
                patch.dict(os.environ, {"MATERIAL_UPLOAD_STORAGE_DIR": temp_dir}),
                patch.object(route, "current_user_id", return_value=user_id),
                patch.object(route, "_require_project_reviewer", return_value=None),
                patch.object(route, "ingest_markdown_memory") as ingest,
                patch.object(
                    route,
                    "ingest_file",
                    return_value=SimpleNamespace(
                        document_id=raw_document_id,
                        chunk_count=2,
                        status="ready",
                        error=None,
                    ),
                ) as ingest_original,
                patch.object(route, "publish_approved_candidates") as publish,
                patch.object(route, "record_audit", return_value=None),
            ):
                response = route.approve_project_memory_draft(
                    request=SimpleNamespace(state=SimpleNamespace()),
                    draft_id=draft_id,
                    body=route.ReviewDraftRequest(decision="approve"),
                    orm=orm,
                )
                ingested_path = Path(ingest_original.call_args.args[0])
                self.assertEqual(ingested_path, stored_path)
                self.assertEqual(ingested_path.read_bytes(), b"# Project\n\nRun Docker")

        ingest.assert_not_called()
        ingest_original.assert_called_once()
        publish.assert_not_called()
        self.assertEqual(response.document_id, raw_document_id)
        self.assertEqual(response.chunk_count, 2)
        self.assertEqual(response.wiki_page_count, 0)
        self.assertTrue(any("project_material_intakes" in sql for sql in orm.executed))
        self.assertTrue(any("project_material_documents" in sql for sql in orm.executed))

    def test_approve_meeting_submission_publishes_only_during_review(self) -> None:
        route = _load_module("project_memory_meeting_review_route", "api/routes/v4/project_memory.py")
        orm = _Orm()
        draft_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        meeting_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        def execute(statement, params=None):
            sql = str(statement)
            orm.executed.append(sql)
            orm.params.append(params or {})
            if "FROM public.project_memory_drafts draft" in sql and "FOR UPDATE" in sql:
                return _Result(SimpleNamespace(
                    id=str(draft_id), project_id="00000000-0000-0000-0000-000000000010",
                    department_id="research-direct", status="pending_review",
                    markdown_content="# 周会", title="周会审批", template_version="meeting-summary-submission-v1",
                    intake_id=None, skill_candidates=[], created_by_user_id=str(user_id),
                    submission_id="00000000-0000-0000-0000-000000000030",
                    submission_type="meeting_summary", submission_payload={},
                ))
            return _Result()
        orm.execute = execute

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_require_project_reviewer", return_value=None),
            patch.object(route, "_publish_meeting_submission", return_value=meeting_id) as publish,
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.approve_project_memory_draft(
                request=SimpleNamespace(state=SimpleNamespace()), draft_id=draft_id,
                body=route.ReviewDraftRequest(decision="approve"), orm=orm,
            )

        publish.assert_called_once()
        self.assertEqual(response.resource_id, meeting_id)
        self.assertIsNone(response.document_id)
        self.assertTrue(any("project_memory_submissions" in sql and "status = 'approved'" in sql for sql in orm.executed))
        draft_update_params = next(
            params for sql, params in zip(orm.executed, orm.params)
            if "approved_document_id = :document_id" in sql
        )
        self.assertIsNone(draft_update_params["document_id"])

    def test_approve_repository_submission_replaces_active_repository_only_during_review(self) -> None:
        route = _load_module("project_memory_repository_review_route", "api/routes/v4/project_memory.py")
        orm = _Orm()
        draft_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        def execute(statement, params=None):
            sql = str(statement)
            orm.executed.append(sql)
            orm.params.append(params or {})
            if "FROM public.project_memory_drafts draft" in sql and "FOR UPDATE" in sql:
                return _Result(SimpleNamespace(
                    id=str(draft_id), project_id="00000000-0000-0000-0000-000000000010",
                    department_id="research-direct", status="pending_review",
                    markdown_content="# 仓库", title="仓库审批", template_version="project-repository-submission-v1",
                    intake_id=None, skill_candidates=[], created_by_user_id=str(user_id),
                    submission_id="00000000-0000-0000-0000-000000000030",
                    submission_type="project_repository",
                    submission_payload={"git_url": "https://github.com/example/repo.git", "git_branch": "main"},
                ))
            return _Result()
        orm.execute = execute

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "_require_project_reviewer", return_value=None),
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.approve_project_memory_draft(
                request=SimpleNamespace(state=SimpleNamespace()), draft_id=draft_id,
                body=route.ReviewDraftRequest(decision="approve"), orm=orm,
            )

        self.assertEqual(response.resource_id, uuid.UUID("00000000-0000-0000-0000-000000000010"))
        self.assertTrue(any("INSERT INTO public.project_repositories" in sql for sql in orm.executed))
        self.assertTrue(any("project_memory_submissions" in sql and "status = 'approved'" in sql for sql in orm.executed))
        draft_update_params = next(
            params for sql, params in zip(orm.executed, orm.params)
            if "approved_document_id = :document_id" in sql
        )
        self.assertIsNone(draft_update_params["document_id"])


class KnowledgeMaterialBatchRouteTests(unittest.TestCase):
    def test_material_batch_upload_ingests_raw_documents_and_creates_review_draft(self) -> None:
        route = _load_module("knowledge_route", "api/routes/v4/knowledge.py")
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        first_doc = uuid.UUID("00000000-0000-0000-0000-000000000031")
        second_doc = uuid.UUID("00000000-0000-0000-0000-000000000032")

        files = [
            route.UploadFile(filename="README.md", file=tempfile.SpooledTemporaryFile()),
            route.UploadFile(filename="app.tsx", file=tempfile.SpooledTemporaryFile()),
        ]
        files[0].file.write("项目启动：pnpm dev".encode("utf-8"))
        files[1].file.write("export const name = '智慧大脑';".encode("utf-8"))
        for file in files:
            file.file.seek(0)

        def execute(statement, params=None):
            sql = str(statement)
            orm.executed.append(sql)
            orm.params.append(params or {})
            if "SELECT name FROM public.departments" in sql:
                return _Result(SimpleNamespace(name="研发"))
            if "INSERT INTO public.project_memory_drafts" in sql:
                return _Result(
                    SimpleNamespace(
                        id=str(uuid.UUID("00000000-0000-0000-0000-000000000020")),
                        project_id=str(project_id),
                        department_id="research",
                        title="测试项目 长期记忆",
                        status="pending_review",
                        markdown_content="# 项目长期记忆：测试项目",
                        source_count=2,
                        approved_document_id=None,
                        created_at="2026-07-28T01:00:00Z",
                        updated_at="2026-07-28T01:00:00Z",
                    )
                )
            return _Result()

        orm.execute = execute

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None),
            patch.object(route, "require_writer", side_effect=AssertionError("writer should not be required")),
            patch.object(route, "_project_name", return_value="测试项目"),
            patch.object(route, "_repository_for_project", return_value=None),
            patch.object(
                route,
                "ingest_file",
                side_effect=[
                    SimpleNamespace(document_id=first_doc, chunk_count=2, status="ready", error=None),
                    SimpleNamespace(document_id=second_doc, chunk_count=1, status="ready", error=None),
                ],
            ) as ingest,
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.knowledge_material_batch_upload(
                request=SimpleNamespace(state=SimpleNamespace()),
                project_id=project_id,
                department_id="research",
                files=files,
                orm=orm,
            )

        self.assertEqual(response.raw_document_count, 2)
        self.assertEqual(response.draft.source_count, 2)
        self.assertEqual([item.filename for item in response.raw_documents], ["README.md", "app.tsx"])
        self.assertEqual(ingest.call_count, 2)
        self.assertTrue(any("INSERT INTO public.project_memory_drafts" in sql for sql in orm.executed))
        material_link_params = [
            params
            for sql, params in zip(orm.executed, orm.params)
            if "INSERT INTO public.project_material_documents" in sql
        ]
        self.assertEqual(
            material_link_params,
            [
                {
                    "project_id": str(project_id),
                    "document_id": str(first_doc),
                    "draft_id": "00000000-0000-0000-0000-000000000020",
                    "user_id": str(user_id),
                },
                {
                    "project_id": str(project_id),
                    "document_id": str(second_doc),
                    "draft_id": "00000000-0000-0000-0000-000000000020",
                    "user_id": str(user_id),
                },
            ],
        )

    def test_knowledge_ledger_returns_project_leaders_and_material_approval_rows(self) -> None:
        route = _load_module("knowledge_route", "api/routes/v4/knowledge.py")
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")

        def execute(statement, params=None):
            sql = str(statement)
            orm.executed.append(sql)
            orm.params.append(params or {})
            if "pm.user_id = :user_id" in sql:
                return _Result(SimpleNamespace(role="developer"))
            if "FROM public.projects p" in sql:
                return _Result(
                    SimpleNamespace(
                        id=str(project_id),
                        name="智慧大脑",
                        environment="development",
                        department_id="research",
                        created_at="2026-07-28T01:00:00Z",
                        completed_at=None,
                    )
                )
            if "FROM public.project_members pm" in sql and "JOIN auth.users" in sql:
                return _Result(
                    rows=[
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
            if "FROM public.documents d" in sql:
                return _Result(
                    rows=[
                        SimpleNamespace(
                            document_id="00000000-0000-0000-0000-000000000031",
                            filename="README.md",
                            display_name="README.md",
                            format="md",
                            size_bytes=120,
                            status="ready",
                            chunk_count=2,
                            error_message=None,
                            uploaded_at="2026-07-28T02:00:00Z",
                            uploaded_by_user_id="00000000-0000-0000-0000-000000000012",
                            uploaded_by_email="member@local.dev",
                            draft_id="00000000-0000-0000-0000-000000000020",
                            draft_status="approved",
                            reviewed_by_user_id="00000000-0000-0000-0000-000000000011",
                            reviewed_by_email="leader@local.dev",
                            reviewed_at="2026-07-28T03:00:00Z",
                            review_comment="通过",
                            approved_memory_document_id="00000000-0000-0000-0000-000000000040",
                        )
                    ]
                )
            return _Result()

        orm.execute = execute

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None) as require_member,
        ):
            ledger = route.get_knowledge_ledger(
                request=object(),
                project_id=project_id,
                uploader_user_id=None,
                approval_status=None,
                uploaded_from=None,
                uploaded_to=None,
                reviewed_from=None,
                reviewed_to=None,
                orm=orm,
            )

        require_member.assert_called_once_with(orm, user_id=user_id, project_id=project_id)
        self.assertFalse(ledger.permissions.can_review)
        self.assertEqual(ledger.project.name, "智慧大脑")
        self.assertEqual(ledger.leaders[0].email, "leader@local.dev")
        self.assertEqual(ledger.summary.raw_document_count, 1)
        self.assertEqual(ledger.summary.approved_count, 1)
        self.assertEqual(ledger.documents[0].uploaded_by.email, "member@local.dev")
        self.assertEqual(ledger.documents[0].reviewed_by.email, "leader@local.dev")
        self.assertEqual(ledger.documents[0].approval_status, "approved")
        self.assertIn("COALESCE(d.memory_type, 'raw_project_material')", "\n".join(orm.executed))

    def test_delete_knowledge_document_requires_project_owner_and_removes_document(self) -> None:
        route = _load_module("knowledge_route", "api/routes/v4/knowledge.py")
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        document_id = uuid.UUID("00000000-0000-0000-0000-000000000031")

        def execute(statement, params=None):
            sql = str(statement)
            orm.executed.append(sql)
            orm.params.append(params or {})
            if "FROM public.documents" in sql:
                return _Result(
                    SimpleNamespace(
                        document_id=str(document_id),
                        project_id=str(project_id),
                        filename="README.md",
                        display_name="README.md",
                        memory_type="raw_project_material",
                    )
                )
            return _Result()

        orm.execute = execute

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_owner", return_value=None) as require_owner,
            patch.object(route, "record_audit") as record_audit,
        ):
            route.delete_knowledge_document(
                request=object(),
                document_id=document_id,
                orm=orm,
            )

        require_owner.assert_called_once_with(orm, user_id=user_id, project_id=project_id)
        self.assertTrue(any("DELETE FROM public.documents" in sql for sql in orm.executed))
        self.assertGreaterEqual(orm.commits, 1)
        record_audit.assert_called_once()
        audit_kwargs = record_audit.call_args.kwargs
        self.assertEqual(audit_kwargs["action"], "delete_document")
        self.assertEqual(audit_kwargs["resource_id"], str(document_id))

    def test_delete_knowledge_document_returns_404_for_missing_document(self) -> None:
        route = _load_module("knowledge_route", "api/routes/v4/knowledge.py")
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        document_id = uuid.UUID("00000000-0000-0000-0000-000000000031")

        with patch.object(route, "current_user_id", return_value=user_id):
            with self.assertRaises(route.HTTPException) as raised:
                route.delete_knowledge_document(
                    request=object(),
                    document_id=document_id,
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(orm.commits, 0)


if __name__ == "__main__":
    unittest.main()
