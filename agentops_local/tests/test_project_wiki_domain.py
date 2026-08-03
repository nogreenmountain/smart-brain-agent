from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_domain():
    path = Path(__file__).parents[1] / "project_wiki" / "domain.py"
    spec = importlib.util.spec_from_file_location("project_wiki_domain_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectWikiDomainTests(unittest.TestCase):
    def test_high_value_procedure_is_auto_applied(self) -> None:
        domain = _load_domain()

        candidate = domain.KnowledgeCandidate(
            title="AI Monitor 后台同步不闪窗",
            page_type="procedure",
            summary="后台同步通过 wscript 隐藏启动 PowerShell。",
            markdown_content=(
                "# AI Monitor 后台同步不闪窗\n\n"
                "计划任务执行 `wscript.exe`，再由 VBS 隐藏启动 PowerShell。"
            ),
            usefulness=0.94,
            confidence=0.96,
            source_ids=["chat:session-1", "document:doc-1"],
            link_titles=["AI Monitor"],
            contradiction=False,
            sensitive=False,
            ephemeral=False,
        )

        decision = domain.classify_candidate(candidate)

        self.assertEqual(decision.disposition, "auto_apply")
        self.assertEqual(decision.reason_code, "high_value_low_risk")

    def test_important_decision_requires_review_even_with_high_score(self) -> None:
        domain = _load_domain()
        candidate = domain.KnowledgeCandidate(
            title="项目权限口径",
            page_type="decision",
            summary="项目知识只允许项目成员读取。",
            markdown_content="# 项目权限口径\n\n项目知识只允许项目成员读取。",
            usefulness=0.98,
            confidence=0.99,
            source_ids=["document:doc-2"],
            link_titles=["项目权限"],
            contradiction=False,
            sensitive=False,
            ephemeral=False,
        )

        decision = domain.classify_candidate(candidate)

        self.assertEqual(decision.disposition, "pending_review")
        self.assertEqual(decision.reason_code, "governed_page_type")

    def test_low_value_or_ephemeral_content_is_discarded(self) -> None:
        domain = _load_domain()
        candidate = domain.KnowledgeCandidate(
            title="午饭后继续",
            page_type="note",
            summary="员工说午饭后继续处理。",
            markdown_content="# 午饭后继续\n\n下午继续。",
            usefulness=0.31,
            confidence=0.94,
            source_ids=["chat:session-3"],
            link_titles=[],
            contradiction=False,
            sensitive=False,
            ephemeral=True,
        )

        decision = domain.classify_candidate(candidate)

        self.assertEqual(decision.disposition, "discard")
        self.assertEqual(decision.reason_code, "ephemeral")

    def test_sensitive_content_is_discarded_regardless_of_model_score(self) -> None:
        domain = _load_domain()
        candidate = domain.KnowledgeCandidate(
            title="生产密钥",
            page_type="procedure",
            summary="记录生产 API key。",
            markdown_content="# 生产密钥\n\nANTHROPIC_AUTH_TOKEN=sk-ant-secret-value",
            usefulness=1.0,
            confidence=1.0,
            source_ids=["chat:session-4"],
            link_titles=[],
            contradiction=False,
            sensitive=False,
            ephemeral=False,
        )

        decision = domain.classify_candidate(candidate)

        self.assertEqual(decision.disposition, "discard")
        self.assertEqual(decision.reason_code, "sensitive_content")

    def test_personal_contact_details_are_discarded(self) -> None:
        domain = _load_domain()
        candidate = domain.KnowledgeCandidate(
            title="项目联系人",
            page_type="fact",
            summary="联系人邮箱 admin@example.com，手机号 13800138000。",
            markdown_content="# 项目联系人\n\n联系 admin@example.com。",
            usefulness=0.95,
            confidence=0.95,
            source_ids=["document:doc-pii"],
            link_titles=[],
            contradiction=False,
            sensitive=False,
            ephemeral=False,
        )

        decision = domain.classify_candidate(candidate)

        self.assertEqual(decision.disposition, "discard")
        self.assertEqual(decision.reason_code, "sensitive_content")

    def test_contradiction_requires_review(self) -> None:
        domain = _load_domain()
        candidate = domain.KnowledgeCandidate(
            title="默认检索版本",
            page_type="fact",
            summary="默认检索版本已经由 v1 改为 v2。",
            markdown_content="# 默认检索版本\n\n默认检索版本已经由 v1 改为 v2。",
            usefulness=0.91,
            confidence=0.93,
            source_ids=["document:doc-5"],
            link_titles=["RAG v2"],
            contradiction=True,
            sensitive=False,
            ephemeral=False,
        )

        decision = domain.classify_candidate(candidate)

        self.assertEqual(decision.disposition, "pending_review")
        self.assertEqual(decision.reason_code, "contradiction")

    def test_model_json_code_fence_is_parsed_and_normalized(self) -> None:
        domain = _load_domain()
        raw = """```json
        {
          "items": [
            {
              "title": "  RAG v2 检索流程  ",
              "page_type": "procedure",
              "summary": "混合召回后进行重排。",
              "markdown_content": "# RAG v2 检索流程\\n\\n向量与关键词混合召回。",
              "usefulness": 0.9,
              "confidence": 0.92,
              "source_ids": ["document:doc-6"],
              "link_titles": ["BGE-M3", "BGE-M3"],
              "contradiction": false,
              "sensitive": false,
              "ephemeral": false
            }
          ]
        }
        ```"""

        candidates = domain.parse_candidate_response(raw)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].title, "RAG v2 检索流程")
        self.assertEqual(candidates[0].link_titles, ["BGE-M3"])
        self.assertTrue(candidates[0].page_key.startswith("procedure-"))

    def test_model_output_preserves_enterprise_memory_metadata(self) -> None:
        domain = _load_domain()
        raw = r"""{
          "items": [
            {
              "title": "安装包首次同步失败",
              "page_type": "troubleshooting",
              "memory_kind": "failure_case",
              "tags": ["AI Monitor", "安装", "AI Monitor"],
              "summary": "旧记录同步失败不应阻断安装。",
              "markdown_content": "# 安装包首次同步失败\n\n首次同步错误应后台重试。",
              "usefulness": 0.93,
              "confidence": 0.96,
              "source_ids": ["document:doc-7"],
              "link_titles": ["AI Monitor 安装流程"],
              "contradiction": false,
              "sensitive": false,
              "ephemeral": false,
              "valid_from": "2026-07-29",
              "valid_until": null
            }
          ]
        }"""

        candidate = domain.parse_candidate_response(raw)[0]

        self.assertEqual(candidate.memory_kind, "failure_case")
        self.assertEqual(candidate.tags, ["AI Monitor", "安装"])
        self.assertEqual(candidate.valid_from, "2026-07-29")
        self.assertIsNone(candidate.valid_until)


if __name__ == "__main__":
    unittest.main()
