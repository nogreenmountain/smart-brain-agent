from __future__ import annotations

import unittest
import os
from pathlib import Path


class UnifiedContentApprovalMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = (
            Path(os.environ.get("AGENTOPS_REPO_ROOT", Path(__file__).parents[2]))
            / "supabase"
            / "migrations"
            / "20260818030000_unify_content_approval_and_knowledge_assets.sql"
        ).read_text(encoding="utf-8")

    def test_creates_generic_submission_table_for_meetings_and_repositories(self) -> None:
        self.assertIn("CREATE TABLE IF NOT EXISTS public.project_memory_submissions", self.sql)
        self.assertIn("submission_type IN ('meeting_summary', 'project_repository')", self.sql)
        self.assertIn("payload jsonb NOT NULL", self.sql)
        self.assertIn("raw_content bytea", self.sql)
        self.assertIn("approved_resource_id uuid", self.sql)

    def test_links_drafts_and_published_meetings_without_deleting_history(self) -> None:
        self.assertIn("ADD COLUMN IF NOT EXISTS submission_id uuid", self.sql)
        self.assertIn("REFERENCES public.project_memory_submissions(id) ON DELETE SET NULL", self.sql)
        self.assertIn("ADD COLUMN IF NOT EXISTS approval_draft_id uuid", self.sql)
        self.assertIn("REFERENCES public.project_memory_drafts(id) ON DELETE SET NULL", self.sql)

    def test_only_one_pending_repository_submission_is_allowed_per_project(self) -> None:
        self.assertIn("uq_project_memory_pending_repository_submission", self.sql)
        self.assertIn("submission_type = 'project_repository'", self.sql)
        self.assertIn("status = 'pending_review'", self.sql)


if __name__ == "__main__":
    unittest.main()
