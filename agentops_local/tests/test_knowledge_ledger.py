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
            "KNOWLEDGE_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "knowledge.py",
        )
    )
    spec = importlib.util.spec_from_file_location("knowledge_route_under_test", route_path)
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


class _LedgerOrm:
    def __init__(self, *, role: str | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.role = role

    def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "FROM public.projects p" in sql:
            return _Result(
                first=SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000010",
                    name="智慧大脑agent",
                    environment="development",
                    department_id="research",
                    created_at="2026-08-01 00:00:00+00",
                    completed_at=None,
                )
            )
        if "SELECT pm.role::text AS role" in sql:
            return _Result(
                first=SimpleNamespace(role=self.role) if self.role is not None else None
            )
        return _Result(rows=[])


class _ActionOrm:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "SELECT department_id FROM public.projects" in sql:
            return _Result(first=SimpleNamespace(department_id="target-direct"))
        return _Result()

    def commit(self):
        self.commits += 1


class KnowledgeLedgerTests(unittest.TestCase):
    def _call(self, *, category: str, system_admin: bool = False, role: str | None = None):
        orm = _LedgerOrm(role=role)
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=system_admin),
            patch.object(route, "require_member", return_value=None),
        ):
            response = route.get_knowledge_ledger(
                request=object(),
                project_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
                category=category,
                uploader_user_id=None,
                approval_status=None,
                uploaded_from=None,
                uploaded_to=None,
                reviewed_from=None,
                reviewed_to=None,
                orm=orm,
            )
        return response, orm

    def test_project_material_category_only_selects_raw_project_materials(self) -> None:
        response, orm = self._call(category="project_material")

        self.assertEqual(response.category, "project_material")
        sql = "\n".join(statement for statement, _ in orm.calls)
        self.assertIn(
            "COALESCE(d.memory_type, 'raw_project_material') = 'raw_project_material'",
            sql,
        )
        self.assertIn(
            "COALESCE(doc.memory_type, 'raw_project_material') = 'raw_project_material'",
            sql,
        )

    def test_project_wiki_source_category_only_selects_wiki_source_documents(self) -> None:
        response, orm = self._call(category="project_wiki_source")

        self.assertEqual(response.category, "project_wiki_source")
        sql = "\n".join(statement for statement, _ in orm.calls)
        self.assertIn("d.memory_type = 'project_wiki_page'", sql)
        self.assertIn("doc.memory_type = 'project_wiki_page'", sql)

    def test_meeting_record_category_selects_published_meetings(self) -> None:
        response, orm = self._call(category="meeting_record")

        self.assertEqual(response.category, "meeting_record")
        sql = "\n".join(statement for statement, _ in orm.calls)
        self.assertIn("FROM public.meeting_summaries", sql)
        self.assertIn("approval_draft_id", sql)

    def test_system_administrator_can_review_any_project_ledger(self) -> None:
        response, _ = self._call(category="project_material", system_admin=True)

        self.assertTrue(response.permissions.can_review)
        self.assertTrue(response.permissions.can_manage)
        self.assertTrue(response.permissions.can_delete)

    def test_material_move_updates_documents_all_chunk_indexes_and_material_link(self) -> None:
        orm = _ActionOrm()
        source_project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        target_project_id = uuid.UUID("00000000-0000-0000-0000-000000000020")
        row = SimpleNamespace(
            asset_id="00000000-0000-0000-0000-000000000030",
            document_id="00000000-0000-0000-0000-000000000030",
            project_id=str(source_project_id), name="README",
        )
        with (
            patch.object(route, "_asset_user", return_value=uuid.uuid4()),
            patch.object(route, "_require_asset", return_value=row),
            patch.object(route, "_asset_authorize", return_value=None) as authorize,
            patch.object(route, "record_audit", return_value=None),
        ):
            result = route.move_knowledge_asset(
                request=object(), asset_type="project_material",
                asset_id=uuid.UUID(str(row.asset_id)),
                body=route.KnowledgeAssetMoveRequest(target_project_id=target_project_id),
                orm=orm,
            )

        self.assertEqual(result.project_id, target_project_id)
        self.assertEqual(authorize.call_count, 2)
        sql = "\n".join(statement for statement, _ in orm.calls)
        self.assertIn("UPDATE public.documents", sql)
        self.assertIn("UPDATE public.document_chunks SET project_id", sql)
        self.assertIn("UPDATE public.document_chunks_v2 SET project_id", sql)
        self.assertIn("UPDATE public.project_material_documents SET project_id", sql)
        self.assertEqual(orm.commits, 1)

    def test_material_asset_query_derives_mime_type_without_nonexistent_file_column(self) -> None:
        orm = _ActionOrm()

        route._load_asset(
            orm,
            asset_type="project_material",
            asset_id=uuid.UUID("00000000-0000-0000-0000-000000000030"),
        )

        sql = "\n".join(statement for statement, _ in orm.calls)
        self.assertNotIn("file.mime_type", sql)
        self.assertIn("CASE d.format", sql)

    def test_wiki_rename_synchronizes_page_and_search_document(self) -> None:
        orm = _ActionOrm()
        row = SimpleNamespace(
            asset_id="00000000-0000-0000-0000-000000000030",
            document_id="00000000-0000-0000-0000-000000000040",
            project_id="00000000-0000-0000-0000-000000000010", name="旧标题",
            markdown_content="# 旧标题\n\n正文",
        )
        with (
            patch.object(route, "_asset_user", return_value=uuid.uuid4()),
            patch.object(route, "_require_asset", return_value=row),
            patch.object(route, "_asset_authorize", return_value=None),
            patch.object(route, "ingest_markdown_memory", return_value=SimpleNamespace(
                document_id=uuid.UUID("00000000-0000-0000-0000-000000000050"),
                error=None,
            )),
            patch.object(route, "record_audit", return_value=None),
        ):
            route.rename_knowledge_asset(
                request=object(), asset_type="project_wiki",
                asset_id=uuid.UUID(str(row.asset_id)),
                body=route.KnowledgeAssetRenameRequest(name="新标题"), orm=orm,
            )

        sql = "\n".join(statement for statement, _ in orm.calls)
        self.assertIn("UPDATE public.project_wiki_pages", sql)
        self.assertIn("project_wiki_page_versions", sql)
        self.assertIn("DELETE FROM public.documents", sql)

    def test_meeting_delete_uses_owner_permission_and_cascading_summary_delete(self) -> None:
        orm = _ActionOrm()
        row = SimpleNamespace(
            asset_id="00000000-0000-0000-0000-000000000030",
            project_id="00000000-0000-0000-0000-000000000010", name="周会",
        )
        with (
            patch.object(route, "_asset_user", return_value=uuid.uuid4()),
            patch.object(route, "_require_asset", return_value=row),
            patch.object(route, "_asset_authorize", return_value=None) as authorize,
            patch.object(route, "record_audit", return_value=None),
        ):
            route.delete_knowledge_asset(
                request=object(), asset_type="meeting_record",
                asset_id=uuid.UUID(str(row.asset_id)), orm=orm,
            )

        self.assertIs(authorize.call_args.args[0], route.require_owner)
        self.assertTrue(any("DELETE FROM public.meeting_summaries" in sql for sql, _ in orm.calls))

    def test_project_lead_can_review_but_cannot_delete_project_materials(self) -> None:
        response, _ = self._call(category="project_material", role="admin")

        self.assertTrue(response.permissions.can_review)
        self.assertTrue(response.permissions.can_manage)
        self.assertFalse(response.permissions.can_delete)

    def test_overall_lead_can_review_and_delete_project_materials(self) -> None:
        response, _ = self._call(category="project_material", role="owner")

        self.assertTrue(response.permissions.can_review)
        self.assertTrue(response.permissions.can_manage)
        self.assertTrue(response.permissions.can_delete)


if __name__ == "__main__":
    unittest.main()
