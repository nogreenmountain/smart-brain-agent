from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_route():
    path = Path(
        os.environ.get(
            "PROJECT_MATERIALS_ROUTE_PATH",
            Path(__file__).parents[1] / "api" / "routes" / "v4" / "project_materials.py",
        )
    )
    spec = importlib.util.spec_from_file_location("project_materials_route_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _Orm:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.file_insert_count = 0
        self.intake = None
        self.files = []

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        if "SELECT content_hash" in sql:
            return _Result(rows=[])
        if "INSERT INTO public.project_material_intakes" in sql:
            return _Result(SimpleNamespace(id="00000000-0000-0000-0000-000000000040"))
        if "INSERT INTO public.project_material_intake_files" in sql:
            self.file_insert_count += 1
            return _Result(
                SimpleNamespace(id=f"00000000-0000-0000-0000-{self.file_insert_count:012d}")
            )
        if "FROM public.project_material_intakes" in sql and "FOR UPDATE" in sql:
            return _Result(self.intake)
        if "FROM public.project_material_intake_files" in sql:
            return _Result(rows=self.files)
        if "SELECT name FROM public.projects" in sql:
            return _Result(SimpleNamespace(name="Smart Brain"))
        if "INSERT INTO public.project_memory_drafts" in sql:
            return _Result(SimpleNamespace(id="00000000-0000-0000-0000-000000000050"))
        return _Result()

    def commit(self):
        self.commits += 1


class ProjectMaterialsRouteTests(unittest.TestCase):
    def test_preview_stores_pending_files_without_ingesting_documents(self) -> None:
        route = _load_route()
        orm = _Orm()
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        files = []
        for filename, content in (("README.md", b"# Project\n\nRun docker compose up."), ("debug.log", b"INFO repeated\nINFO repeated")):
            handle = tempfile.SpooledTemporaryFile()
            handle.write(content)
            handle.seek(0)
            files.append(route.UploadFile(filename=filename, file=handle))
        sources = [
            route.MaterialSource("README.md", "md", "# Project", 32, "hash-1"),
            route.MaterialSource("debug.log", "log", "INFO repeated", 28, "hash-2"),
        ]
        preview = SimpleNamespace(
            summary="建议保存 1 个",
            model="MiniMax-M3",
            used_fallback=False,
            items=(
                SimpleNamespace(filename="README.md", format="md", size_bytes=32, content_hash="hash-1", recommendation="keep", included=True, reason="useful", issues=()),
                SimpleNamespace(filename="debug.log", format="log", size_bytes=28, content_hash="hash-2", recommendation="low_value", included=False, reason="temporary", issues=("low_value",)),
            ),
        )

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None),
            patch.object(route, "_extract_source", side_effect=sources),
            patch.object(route, "preview_materials", return_value=preview),
            patch.object(route, "ingest_file") as ingest,
        ):
            response = route.preview_project_materials(
                request=object(),
                project_id=project_id,
                department_id="research",
                files=files,
                orm=orm,
            )

        ingest.assert_not_called()
        self.assertEqual(response.status, "preview_ready")
        self.assertEqual(len(response.items), 2)
        self.assertEqual(orm.file_insert_count, 2)
        inserts = [
            params
            for sql, params in orm.calls
            if "INSERT INTO public.project_material_intake_files" in sql
        ]
        self.assertEqual(inserts[0]["raw_content"], b"# Project\n\nRun docker compose up.")
        self.assertEqual(inserts[0]["extracted_text"], "# Project")
        self.assertEqual(inserts[1]["raw_content"], b"")
        self.assertEqual(inserts[1]["extracted_text"], "")

    def test_confirm_ignores_sensitive_file_even_when_client_requests_it(self) -> None:
        route = _load_route()
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        intake_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        keep_id = "00000000-0000-0000-0000-000000000041"
        secret_id = "00000000-0000-0000-0000-000000000042"
        orm.intake = SimpleNamespace(
            id=str(intake_id),
            project_id=str(project_id),
            department_id="research",
            status="preview_ready",
            created_by_user_id=str(user_id),
        )
        orm.files = [
            SimpleNamespace(id=keep_id, filename="README.md", format="md", size_bytes=30, content_hash="hash-1", raw_content=b"# Project\n\nRun Docker", extracted_text="# Project\n\nRun Docker", recommendation="keep", included=True),
            SimpleNamespace(id=secret_id, filename=".env.txt", format="txt", size_bytes=30, content_hash="hash-2", raw_content=b"TOKEN=secret", extracted_text="TOKEN=secret", recommendation="sensitive", included=False),
        ]
        skill = SimpleNamespace(
            title="Run locally",
            summary="Start the project",
            markdown_content="# Run locally\n\n1. Start services",
            source_filenames=("README.md",),
        )
        package = SimpleNamespace(
            curated_markdown="# Curated\n\nRun Docker.\n",
            skills=(skill,),
            model="MiniMax-M3",
            used_fallback=False,
        )
        raw_document_id = uuid.UUID("00000000-0000-0000-0000-000000000060")
        curated_document_id = uuid.UUID("00000000-0000-0000-0000-000000000061")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None),
            patch.object(route, "generate_knowledge_package", return_value=package),
            patch.object(route, "_write_temp_file", return_value=Path(__file__)),
            patch.object(route.Path, "unlink", return_value=None),
            patch.object(route, "ingest_file", return_value=SimpleNamespace(document_id=raw_document_id, chunk_count=1, status="ready", error=None)) as ingest,
            patch.object(route, "ingest_markdown_memory", return_value=SimpleNamespace(document_id=curated_document_id, chunk_count=1, status="ready", error=None)),
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.confirm_project_materials(
                request=object(),
                intake_id=intake_id,
                body=route.ConfirmMaterialIntakeRequest(
                    included_file_ids=[uuid.UUID(keep_id), uuid.UUID(secret_id)]
                ),
                orm=orm,
            )

        self.assertEqual(ingest.call_count, 1)
        self.assertEqual(response.raw_document_count, 1)
        self.assertEqual(response.skill_count, 1)


if __name__ == "__main__":
    unittest.main()
