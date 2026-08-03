from __future__ import annotations

import importlib.util
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


def _load_query():
    path = Path(__file__).parents[1] / "project_wiki" / "query.py"
    spec = importlib.util.spec_from_file_location("project_wiki_query_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectWikiQueryTests(unittest.TestCase):
    def test_semantic_search_does_not_start_the_legacy_local_model_when_v2_is_empty(self) -> None:
        query = _load_query()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")

        with patch.object(query, "rag_search", return_value=[]) as search:
            result = query._semantic_page_scores(
                object(),
                query="deployment",
                project_id=project_id,
                limit=5,
            )

        self.assertEqual(result, {})
        search.assert_called_once_with(
            unittest.mock.ANY,
            query="deployment",
            project_id=project_id,
            k=20,
            retrieval_version="v2-hybrid",
        )

    def test_optional_filters_are_explicitly_typed_for_postgres(self) -> None:
        query = _load_query()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")

        class Result:
            def mappings(self):
                return self

            def all(self):
                return []

        class Orm:
            def __init__(self):
                self.sql = []

            def execute(self, statement, params=None):
                self.sql.append(str(statement))
                return Result()

        orm = Orm()
        query._keyword_page_scores(
            orm,
            query="deploy",
            project_id=project_id,
            memory_kinds=None,
            tags=None,
            updated_after=None,
            verified_only=False,
            limit=5,
        )
        query._load_pages(
            orm,
            page_ids=[uuid.UUID("00000000-0000-0000-0000-000000000020")],
            project_id=project_id,
            memory_kinds=None,
            tags=None,
            updated_after=None,
            verified_only=False,
        )
        query.get_recent_updates(
            orm,
            project_id=project_id,
            since=None,
            memory_kinds=None,
        )

        combined = "\n".join(orm.sql)
        self.assertIn("CAST(:updated_after AS timestamptz) IS NULL", combined)
        self.assertIn("CAST(:memory_kinds AS text[]) IS NULL", combined)
        self.assertIn("CAST(:tags AS text[]) IS NULL", combined)
        self.assertIn("CAST(:since AS timestamptz) IS NULL", combined)

    def test_search_fuses_keyword_and_semantic_scores_into_compact_page_hits(self) -> None:
        query = _load_query()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        page_a = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
        page_b = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
        pages = {
            page_a: query.WikiPageRecord(
                id=page_a,
                project_id=project_id,
                title="AI Monitor 首次同步失败",
                page_type="troubleshooting",
                memory_kind="failure_case",
                tags=["AI Monitor", "安装"],
                summary="首次同步错误不应阻断安装。",
                markdown_content="# AI Monitor 首次同步失败\n\n后台任务继续重试。",
                usefulness=0.94,
                confidence=0.96,
                verification_status="verified",
                current_version=2,
                updated_at="2026-08-03T03:00:00+00:00",
            ),
            page_b: query.WikiPageRecord(
                id=page_b,
                project_id=project_id,
                title="AI Monitor 安装流程",
                page_type="procedure",
                memory_kind="workflow_template",
                tags=["AI Monitor"],
                summary="标准安装步骤。",
                markdown_content="# AI Monitor 安装流程\n\n执行安装器。",
                usefulness=0.9,
                confidence=0.93,
                verification_status="generated",
                current_version=1,
                updated_at="2026-08-02T03:00:00+00:00",
            ),
        }

        with (
            patch.object(query, "_keyword_page_scores", return_value={page_a: (0.9, "首次同步错误")}),
            patch.object(query, "_semantic_page_scores", return_value={page_a: (0.8, "后台任务继续重试"), page_b: (0.95, "标准安装步骤")}),
            patch.object(query, "_load_pages", return_value=pages),
        ):
            hits = query.search_wiki(
                object(),
                query="安装失败如何处理",
                project_id=project_id,
                memory_kinds=["failure_case", "workflow_template"],
                limit=5,
            )

        self.assertEqual([hit.page_id for hit in hits], [page_a, page_b])
        self.assertEqual(hits[0].verification_status, "verified")
        self.assertIn("首次同步", hits[0].matched_excerpt)
        self.assertLessEqual(len(hits[0].matched_excerpt), 320)
        self.assertGreater(hits[0].score, hits[1].score)

    def test_examples_only_return_example_memory_kinds(self) -> None:
        query = _load_query()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")

        with patch.object(query, "search_wiki", return_value=[]) as search:
            query.get_examples(
                object(),
                topic="安装",
                project_id=project_id,
                outcome="failure",
                limit=4,
            )

        search.assert_called_once_with(
            unittest.mock.ANY,
            query="安装",
            project_id=project_id,
            memory_kinds=["failure_case"],
            limit=4,
        )


if __name__ == "__main__":
    unittest.main()
