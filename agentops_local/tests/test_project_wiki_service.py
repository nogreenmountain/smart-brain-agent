from __future__ import annotations

import importlib.util
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch


def _load_module(name: str, relative: str):
    path = Path(__file__).parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectWikiServiceTests(unittest.TestCase):
    def test_compile_routes_candidates_to_apply_review_and_discard(self) -> None:
        domain = _load_module("project_wiki_domain_for_service_test", "project_wiki/domain.py")
        compiler = _load_module("project_wiki_compiler_for_service_test", "project_wiki/compiler.py")
        service = _load_module("project_wiki_service_under_test", "project_wiki/service.py")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        run_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        source = compiler.WikiSource(
            source_id="chat:session-1",
            source_type="ai_chat_session",
            title="修复记录",
            content="通过 wscript 隐藏 PowerShell。",
            observed_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
        candidates = [
            domain.KnowledgeCandidate(
                title="后台同步不闪窗",
                page_type="procedure",
                summary="使用 wscript 隐藏 PowerShell。",
                markdown_content="# 后台同步不闪窗\n\n使用 wscript 隐藏 PowerShell。",
                usefulness=0.95,
                confidence=0.96,
                source_ids=[source.source_id],
                link_titles=[],
                contradiction=False,
                sensitive=False,
                ephemeral=False,
            ),
            domain.KnowledgeCandidate(
                title="安装权限口径",
                page_type="decision",
                summary="安装不再要求默认项目成员。",
                markdown_content="# 安装权限口径\n\n安装不再要求默认项目成员。",
                usefulness=0.98,
                confidence=0.99,
                source_ids=[source.source_id],
                link_titles=[],
                contradiction=False,
                sensitive=False,
                ephemeral=False,
            ),
            domain.KnowledgeCandidate(
                title="明天继续",
                page_type="note",
                summary="明天继续处理。",
                markdown_content="# 明天继续\n\n明天继续处理。",
                usefulness=0.2,
                confidence=0.9,
                source_ids=[source.source_id],
                link_titles=[],
                contradiction=False,
                sensitive=False,
                ephemeral=True,
            ),
        ]
        orm = Mock()

        with (
            patch.object(service, "_insert_compile_run", return_value=run_id),
            patch.object(
                service,
                "collect_incremental_sources",
                return_value=[source],
            ) as collect_sources,
            patch.object(service, "load_existing_pages", return_value=[]),
            patch.object(service, "generate_candidates", return_value=candidates),
            patch.object(service, "_apply_candidate") as apply_candidate,
            patch.object(service, "_persist_change") as persist_change,
            patch.object(service, "_mark_sources_processed") as mark_processed,
            patch.object(service, "_finish_compile_run") as finish_run,
        ):
            result = service.compile_project_wiki(
                orm,
                project_id=project_id,
                project_name="智慧大脑",
                triggered_by_user_id=user_id,
            )

        self.assertEqual(result.auto_applied_count, 1)
        self.assertEqual(result.pending_review_count, 1)
        self.assertEqual(result.discarded_count, 1)
        collect_sources.assert_called_once_with(
            orm,
            project_id=project_id,
            limit_per_type=10,
            include_ai_chat_sources=False,
        )
        apply_candidate.assert_called_once()
        self.assertEqual(persist_change.call_count, 2)
        mark_processed.assert_called_once()
        finish_run.assert_called_once()

    def test_compile_without_new_sources_finishes_without_calling_model(self) -> None:
        service = _load_module("project_wiki_service_empty_under_test", "project_wiki/service.py")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        run_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        orm = Mock()

        with (
            patch.object(service, "_insert_compile_run", return_value=run_id),
            patch.object(service, "collect_incremental_sources", return_value=[]),
            patch.object(service, "generate_candidates") as generate,
            patch.object(service, "_finish_compile_run") as finish_run,
        ):
            result = service.compile_project_wiki(
                orm,
                project_id=project_id,
                project_name="智慧大脑",
                triggered_by_user_id=None,
            )

        self.assertEqual(result.source_count, 0)
        self.assertEqual(result.candidate_count, 0)
        generate.assert_not_called()
        finish_run.assert_called_once()

    def test_source_queries_skip_processed_rows_before_applying_limit(self) -> None:
        service = _load_module(
            "project_wiki_service_incremental_query_under_test",
            "project_wiki/service.py",
        )
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm = Mock()
        orm.execute.return_value.all.return_value = []

        service._chat_sources(orm, project_id, 10)
        chat_query = str(orm.execute.call_args.args[0])
        self.assertIn("project_wiki_processed_sources", chat_query)
        self.assertIn("processed.observed_at IS DISTINCT FROM s.updated_at", chat_query)

        service._document_sources(orm, project_id, 10)
        document_query = str(orm.execute.call_args.args[0])
        self.assertIn("project_wiki_processed_sources", document_query)
        self.assertIn("processed.observed_at IS DISTINCT FROM d.updated_at", document_query)
        self.assertIn("raw_project_material", document_query)
        self.assertIn("curated_project_source", document_query)

    def test_publish_approved_candidates_applies_every_skill_without_second_review(self) -> None:
        domain = _load_module("project_wiki_domain_for_publish_test", "project_wiki/domain.py")
        service = _load_module("project_wiki_service_publish_under_test", "project_wiki/service.py")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        run_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        candidates = [
            domain.KnowledgeCandidate(
                title="Deploy locally",
                page_type="procedure",
                summary="Start the verified stack.",
                markdown_content="# Deploy locally\n\n1. Start services",
                usefulness=1.0,
                confidence=1.0,
                source_ids=["document:doc-1"],
                link_titles=[],
                contradiction=False,
                sensitive=False,
                ephemeral=False,
            )
        ]
        orm = Mock()

        with (
            patch.object(service, "_insert_compile_run", return_value=run_id),
            patch.object(service, "_apply_candidate") as apply_candidate,
            patch.object(service, "_finish_compile_run") as finish_run,
        ):
            page_ids = service.publish_approved_candidates(
                orm,
                project_id=project_id,
                candidates=candidates,
                approved_by_user_id=user_id,
            )

        self.assertEqual(len(page_ids), 1)
        apply_candidate.assert_called_once()
        finish_run.assert_called_once()
        self.assertEqual(finish_run.call_args.kwargs["pending_review_count"], 0)

    def test_mcp_memory_proposal_is_published_directly(self) -> None:
        service = _load_module("project_wiki_service_proposal_under_test", "project_wiki/service.py")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        run_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        page_id = uuid.UUID("00000000-0000-0000-0000-000000000040")

        with (
            patch.object(service, "_insert_compile_run", return_value=run_id),
            patch.object(service, "_apply_candidate", return_value=page_id) as apply_candidate,
            patch.object(service, "_finish_compile_run") as finish,
        ):
            result = service.create_memory_proposal(
                Mock(),
                project_id=project_id,
                proposed_by_user_id=user_id,
                title="安装包首次同步失败",
                memory_kind="failure_case",
                content="# 安装包首次同步失败\n\n旧记录同步失败不应阻断安装。",
                summary="旧记录同步失败应后台重试。",
                tags=["AI Monitor", "安装"],
                source_page_ids=[],
            )

        self.assertEqual(result, page_id)
        candidate = apply_candidate.call_args.kwargs["candidate"]
        self.assertEqual(candidate.memory_kind, "failure_case")
        self.assertEqual(candidate.tags, ["AI Monitor", "安装"])
        self.assertEqual(apply_candidate.call_args.kwargs["created_by_user_id"], user_id)
        self.assertEqual(apply_candidate.call_args.kwargs["reason_code"], "mcp_direct_publish")
        self.assertEqual(finish.call_args.kwargs["auto_applied_count"], 1)
        self.assertEqual(finish.call_args.kwargs["pending_review_count"], 0)


if __name__ == "__main__":
    unittest.main()
