from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Orm:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        return _Result([
            types.SimpleNamespace(
                id="00000000-0000-0000-0000-000000000001",
                employee_id="test1",
                employee_name="张三",
                experience_key="deploy-dashboard",
                title="部署 Dashboard",
                task_type="deployment",
                outcome="success",
                summary="重建镜像并完成健康检查。",
                markdown_content="# 部署 Dashboard",
                tags=["deployment"],
                tools=["Docker"],
                confidence=0.94,
                first_observed="2026-08-03",
                last_observed="2026-08-04",
                observation_count=2,
                current_version=2,
                updated_at="2026-08-04T13:00:00+00:00",
                lexical_score=0.8,
                vector_score=0.9,
            )
        ])


def _load_module():
    path = Path(__file__).parents[1] / "member_wiki" / "query.py"
    spec = importlib.util.spec_from_file_location("member_wiki_query_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MemberWikiQueryTests(unittest.TestCase):
    def test_search_is_scoped_to_accessible_employee_ids_and_supports_hybrid_vector(self) -> None:
        query = _load_module()
        orm = _Orm()

        items = query.search_member_experiences(
            orm,
            employee_ids=["test1", "test2"],
            query="如何发布新版本",
            tags=["deployment"],
            outcome="success",
            limit=8,
            query_embedding=[0.1] * 1024,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].employee_id, "test1")
        sql, params = orm.calls[0]
        self.assertIn("employee_id = ANY", sql)
        self.assertIn("embedding <=>", sql)
        self.assertEqual(params["employee_ids"], ["test1", "test2"])
        self.assertEqual(params["outcome"], "success")
        self.assertEqual(params["tags"], ["deployment"])

    def test_search_without_embedding_keeps_keyword_fallback(self) -> None:
        query = _load_module()
        orm = _Orm()

        query.search_member_experiences(
            orm,
            employee_ids=["test1"],
            query="登录故障",
            limit=5,
            query_embedding=None,
        )

        sql, _ = orm.calls[0]
        self.assertNotIn("embedding <=>", sql)
        self.assertIn("ILIKE", sql)


if __name__ == "__main__":
    unittest.main()
