from __future__ import annotations

import unittest
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260812010000_add_project_department_migrations.sql"
)
STRICT_MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "supabase"
    / "migrations"
    / "20260812000000_enforce_strict_project_hierarchy.sql"
)


class ProjectDepartmentMigrationSqlTests(unittest.TestCase):
    def test_strict_hierarchy_migration_handles_every_dynamic_root(self) -> None:
        sql = STRICT_MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn("FROM public.departments root", sql)
        self.assertIn("root.parent_id IS NULL", sql)
        self.assertIn("'direct-' || substr(md5(root.id), 1, 32)", sql)
        self.assertIn("DROP CONSTRAINT IF EXISTS departments_sort_order_key", sql)
        for table in (
            "public.projects",
            "public.project_creation_requests",
            "public.project_material_intakes",
            "public.project_memory_drafts",
            "public.documents",
        ):
            self.assertIn(f"UPDATE {table}", sql)

    def test_migration_backfills_and_automates_one_direct_child_per_root(self) -> None:
        sql = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn("ADD COLUMN IF NOT EXISTS is_direct boolean", sql)
        self.assertIn("departments_one_direct_child_per_root_idx", sql)
        self.assertIn("ensure_root_direct_department", sql)
        self.assertIn("直属分级", sql)
        self.assertIn("md5(root.id)", sql)
        self.assertIn("ON DELETE CASCADE", sql)
        self.assertIn("protect_direct_department_delete", sql)
        self.assertIn("pg_trigger_depth() = 1", sql)

    def test_migration_persists_jobs_and_repairs_redundant_project_metadata(self) -> None:
        sql = MIGRATION_PATH.read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS public.project_department_migrations", sql)
        for table in (
            "public.projects",
            "public.documents",
            "public.project_material_intakes",
            "public.project_memory_drafts",
            "public.project_creation_requests",
        ):
            self.assertIn(f"UPDATE {table}", sql)
        self.assertIn("project_department_migration", sql)
        created_request_sync = sql.split(
            "UPDATE public.project_creation_requests request_row"
        )[-1].split("ALTER TABLE public.audit_logs", 1)[0]
        self.assertIn("request_row.created_project_id = project.id", created_request_sync)
        self.assertNotIn("status = 'pending'", created_request_sync)


if __name__ == "__main__":
    unittest.main()
