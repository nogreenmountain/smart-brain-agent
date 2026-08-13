from __future__ import annotations

import unittest
from pathlib import Path


class MeetingContentMigrationTests(unittest.TestCase):
    def test_migration_preserves_legacy_fields_and_adds_original_file_storage(self) -> None:
        migration = (
            Path(__file__).parents[2]
            / "supabase"
            / "migrations"
            / "20260811010000_simplify_meeting_records.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("participant_user_ids uuid[]", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS public.meeting_summary_files", migration)
        self.assertIn("raw_content bytea", migration)
        self.assertIn("extracted_text text", migration)
        self.assertNotIn("DROP COLUMN", migration.upper())


if __name__ == "__main__":
    unittest.main()
