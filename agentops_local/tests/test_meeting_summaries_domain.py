from __future__ import annotations

import unittest
from datetime import date

from agentops.meeting_summaries.domain import build_meeting_markdown, normalize_list


class MeetingSummaryDomainTests(unittest.TestCase):
    def test_normalize_list_accepts_lines_commas_and_deduplicates(self) -> None:
        self.assertEqual(
            normalize_list("张三, 李四\n- 张三\n王五"),
            ["张三", "李四", "王五"],
        )

    def test_builds_canonical_markdown_for_mcp_reuse(self) -> None:
        markdown = build_meeting_markdown(
            title="智慧大脑周会",
            meeting_date=date(2026, 8, 5),
            participants=["张三", "李四"],
            tags=["周会", "MCP"],
            summary="讨论成员 Wiki 与会议摘要检索。",
            decisions=["会议摘要必须归属项目"],
            action_items=["张三：完成 MCP 检索工具"],
        )

        self.assertIn('title: "智慧大脑周会"', markdown)
        self.assertIn("meeting_date: 2026-08-05", markdown)
        self.assertIn("## 会议内容", markdown)
        self.assertNotIn("## 会议摘要", markdown)
        self.assertIn("## 关键决策", markdown)
        self.assertIn("- 会议摘要必须归属项目", markdown)
        self.assertIn("## 行动项", markdown)
        self.assertIn("- [ ] 张三：完成 MCP 检索工具", markdown)


if __name__ == "__main__":
    unittest.main()
