from __future__ import annotations

import unittest
from pathlib import Path


class MeetingSummaryMcpContractTests(unittest.TestCase):
    def test_server_exposes_meeting_summary_tools(self) -> None:
        root = Path(__file__).parents[1]
        server = (root / "wiki_mcp" / "server.py").read_text(encoding="utf-8")
        for tool_name in (
            "list_meeting_summaries",
            "search_meeting_summaries",
            "get_meeting_summary",
        ):
            self.assertIn(f"def {tool_name}(", server)
        self.assertIn("project membership", server)

    def test_operations_use_project_scoped_meeting_query(self) -> None:
        root = Path(__file__).parents[1]
        operations = (root / "wiki_mcp" / "operations.py").read_text(encoding="utf-8")
        self.assertIn("query_search_meeting_summaries", operations)
        self.assertIn("query_get_meeting_summary", operations)
        self.assertIn("_resolve_project", operations)
        self.assertIn('"participant_user_ids"', operations)
        self.assertIn('"source_format"', operations)
        self.assertIn('result["summary_markdown"]', operations)


if __name__ == "__main__":
    unittest.main()
