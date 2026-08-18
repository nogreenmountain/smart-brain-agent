from __future__ import annotations

import unittest
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260818020000_allow_xlsx_documents.sql"
)


class XlsxDocumentFormatMigrationTests(unittest.TestCase):
    def test_documents_and_draft_sources_accept_xlsx(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")

        self.assertIn("DROP CONSTRAINT IF EXISTS documents_format_check", sql)
        self.assertIn("ADD CONSTRAINT documents_format_check", sql)
        self.assertIn("DROP CONSTRAINT IF EXISTS project_memory_draft_sources_format_check", sql)
        self.assertIn("ADD CONSTRAINT project_memory_draft_sources_format_check", sql)
        self.assertGreaterEqual(sql.count("'xlsx'"), 2)


if __name__ == "__main__":
    unittest.main()
