from __future__ import annotations

import unittest
from pathlib import Path


class MemberWikiMcpContractTests(unittest.TestCase):
    def test_server_exposes_member_wiki_tools_for_listing_search_reading_and_recency(self) -> None:
        root = Path(__file__).parents[1]
        server = (root / "wiki_mcp" / "server.py").read_text(encoding="utf-8")

        for tool_name in (
            "list_member_wikis",
            "search_member_experience",
            "get_member_experience",
            "get_member_recent_experience",
        ):
            self.assertIn(f"def {tool_name}(", server)
        self.assertIn("token owner", server)
        self.assertIn("same access", server)

    def test_mcp_operations_use_member_access_context_instead_of_project_membership(self) -> None:
        root = Path(__file__).parents[1]
        operations = (root / "wiki_mcp" / "operations.py").read_text(encoding="utf-8")

        self.assertIn("load_member_access_context", operations)
        self.assertIn("search_member_experiences", operations)
        self.assertIn("get_member_experience", operations)
        self.assertIn("accessible_members", operations)


if __name__ == "__main__":
    unittest.main()
