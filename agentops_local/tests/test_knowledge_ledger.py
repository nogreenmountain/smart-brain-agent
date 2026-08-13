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
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

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
            return _Result(first=None)
        return _Result(rows=[])


class KnowledgeLedgerTests(unittest.TestCase):
    def _call(self, *, category: str, system_admin: bool = False):
        orm = _LedgerOrm()
        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "is_system_admin", return_value=system_admin),
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

    def test_system_administrator_can_review_any_project_ledger(self) -> None:
        response, _ = self._call(category="project_material", system_admin=True)

        self.assertTrue(response.permissions.can_review)


if __name__ == "__main__":
    unittest.main()
