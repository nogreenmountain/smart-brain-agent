from __future__ import annotations

import importlib.util
import os
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_route_module():
    route_path = Path(
        os.environ.get(
            "PROJECT_MEMORY_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "project_memory.py",
        )
    )
    spec = importlib.util.spec_from_file_location("project_memory_route_under_test", route_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load route module from {route_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


route = _load_route_module()


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows


class _ReorderOrm:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.commits = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append(sql)
        if "parent_id IS NOT DISTINCT FROM" in sql and "FOR UPDATE" in sql:
            return _Result([
                SimpleNamespace(
                    id="direct-research",
                    name="直属分级",
                    sort_order=1,
                    parent_id="research",
                    parent_name="研发支撑",
                    allows_projects=True,
                    is_direct=True,
                    level=2,
                ),
                SimpleNamespace(
                    id="custom-research",
                    name="自定义分级",
                    sort_order=2,
                    parent_id="research",
                    parent_name="研发支撑",
                    allows_projects=True,
                    is_direct=False,
                    level=2,
                ),
            ])
        return _Result()

    def commit(self):
        self.commits += 1


class ProjectMemoryReorderLockTests(unittest.TestCase):
    def test_reorder_locks_only_department_rows_when_parent_is_outer_joined(self) -> None:
        orm = _ReorderOrm()
        with (
            patch.object(route, "_system_admin_user", return_value=uuid.uuid4()),
            patch.object(route, "record_audit", return_value=None),
        ):
            rows = route.reorder_project_memory_departments(
                request=SimpleNamespace(state=SimpleNamespace()),
                body=route.ReorderDepartmentsRequest(
                    parent_id="research",
                    department_ids=["custom-research", "direct-research"],
                ),
                orm=orm,
            )

        lock_sql = next(sql for sql in orm.executed if "FOR UPDATE" in sql)
        self.assertIn("FOR UPDATE OF department", lock_sql)
        self.assertEqual([row.id for row in rows], ["custom-research", "direct-research"])
        self.assertEqual(orm.commits, 1)

    def test_reorder_rejects_duplicate_department_ids(self) -> None:
        orm = _ReorderOrm()
        with patch.object(route, "_system_admin_user", return_value=uuid.uuid4()):
            with self.assertRaises(route.HTTPException) as raised:
                route.reorder_project_memory_departments(
                    request=SimpleNamespace(state=SimpleNamespace()),
                    body=route.ReorderDepartmentsRequest(
                        parent_id="research",
                        department_ids=["direct-research", "direct-research"],
                    ),
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(orm.commits, 0)

    def test_reorder_rejects_incomplete_or_cross_parent_lists(self) -> None:
        for department_ids in (
            ["direct-research"],
            ["direct-research", "other-parent-child"],
        ):
            with self.subTest(department_ids=department_ids):
                orm = _ReorderOrm()
                with patch.object(route, "_system_admin_user", return_value=uuid.uuid4()):
                    with self.assertRaises(route.HTTPException) as raised:
                        route.reorder_project_memory_departments(
                            request=SimpleNamespace(state=SimpleNamespace()),
                            body=route.ReorderDepartmentsRequest(
                                parent_id="research",
                                department_ids=department_ids,
                            ),
                            orm=orm,
                        )

                self.assertEqual(raised.exception.status_code, 409)
                self.assertEqual(orm.commits, 0)


if __name__ == "__main__":
    unittest.main()
