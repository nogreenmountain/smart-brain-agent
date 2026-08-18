from __future__ import annotations

import asyncio
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
    def __init__(self, *, project_department_id="research"):
        self.calls = []
        self.commits = 0
        self.file_insert_count = 0
        self.intake = None
        self.files = []
        self.project_department_id = project_department_id

    def execute(self, statement, params=None):
        sql = str(statement)
        values = params or {}
        self.calls.append((sql, values))
        if "SELECT content_hash" in sql:
            return _Result(rows=[])
        if "SELECT department_id" in sql and "FROM public.projects" in sql:
            return _Result(SimpleNamespace(department_id=self.project_department_id))
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
    def test_direct_upload_session_stages_every_file_without_ai_sensitive_scan(self) -> None:
        route = _load_route()
        orm = _Orm(project_department_id="research-direct")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        intake_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        first_file_id = uuid.UUID("00000000-0000-0000-0000-000000000041")
        second_file_id = uuid.UUID("00000000-0000-0000-0000-000000000042")

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None),
            patch.object(route.uuid, "uuid4", side_effect=[intake_id, first_file_id, second_file_id]),
            patch.object(route, "preview_materials", side_effect=AssertionError("AI preview must not run")),
        ):
            response = route.create_material_upload_session(
                request=object(),
                body=route.CreateMaterialUploadSessionRequest(
                    project_id=project_id,
                    department_id="research-direct",
                    client_upload_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
                    files=[
                        route.MaterialUploadManifestFile(filename="需求.docx", size_bytes=1024),
                        route.MaterialUploadManifestFile(filename="方案.pptx", size_bytes=2048),
                    ],
                ),
                orm=orm,
            )

        self.assertEqual(response.intake_id, intake_id)
        self.assertEqual(response.status, "uploading")
        self.assertEqual([item.filename for item in response.files], ["需求.docx", "方案.pptx"])
        self.assertEqual([item.received_bytes for item in response.files], [0, 0])
        inserts = "\n".join(sql for sql, _ in orm.calls)
        self.assertIn("INSERT INTO public.project_material_intakes", inserts)
        self.assertEqual(inserts.count("INSERT INTO public.project_material_intake_files"), 2)

    def test_direct_upload_chunk_is_written_with_real_received_byte_progress(self) -> None:
        route = _load_route()
        orm = _Orm(project_department_id="research-direct")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        intake_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        file_id = uuid.UUID("00000000-0000-0000-0000-000000000041")

        original_execute = orm.execute

        def execute(statement, params=None):
            sql = str(statement)
            if "FROM public.project_material_intake_files file" in sql:
                orm.calls.append((sql, params or {}))
                return _Result(SimpleNamespace(
                    id=str(file_id),
                    intake_id=str(intake_id),
                    project_id=str(project_id),
                    status="uploading",
                    created_by_user_id=str(user_id),
                    filename="方案.pptx",
                    size_bytes=11,
                    storage_key=f"{project_id}/{intake_id}/{file_id}.pptx",
                    uploaded_bytes=0,
                ))
            return original_execute(statement, params)

        orm.execute = execute

        class ChunkRequest:
            state = SimpleNamespace()

            async def body(self):
                return b"hello"

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"MATERIAL_UPLOAD_STORAGE_DIR": temp_dir}
        ), patch.object(route, "current_user_id", return_value=user_id), patch.object(
            route, "require_member", return_value=None
        ):
            response = asyncio.run(route.upload_material_chunk(
                request=ChunkRequest(),
                intake_id=intake_id,
                file_id=file_id,
                offset=0,
                orm=orm,
            ))

        self.assertEqual(response.received_bytes, 5)
        self.assertEqual(response.size_bytes, 11)
        update = next(params for sql, params in orm.calls if "SET uploaded_bytes" in sql)
        self.assertEqual(update["uploaded_bytes"], 5)

    def test_direct_upload_reads_slow_chunk_before_acquiring_database_connection(self) -> None:
        route = _load_route()
        orm = _Orm(project_department_id="research-direct")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        intake_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        file_id = uuid.UUID("00000000-0000-0000-0000-000000000041")

        original_execute = orm.execute

        def execute(statement, params=None):
            sql = str(statement)
            if "FROM public.project_material_intake_files file" in sql:
                orm.calls.append((sql, params or {}))
                return _Result(SimpleNamespace(
                    id=str(file_id),
                    intake_id=str(intake_id),
                    project_id=str(project_id),
                    status="uploading",
                    created_by_user_id=str(user_id),
                    filename="slow.md",
                    size_bytes=5,
                    storage_key=f"{project_id}/{intake_id}/{file_id}.md",
                    uploaded_bytes=0,
                ))
            return original_execute(statement, params)

        orm.execute = execute

        class SlowChunkRequest:
            state = SimpleNamespace()

            async def body(self):
                self.assert_no_database_connection_yet()
                await asyncio.sleep(0)
                return b"hello"

            @staticmethod
            def assert_no_database_connection_yet():
                if orm.calls:
                    raise AssertionError("database connection was acquired before chunk receipt")

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"MATERIAL_UPLOAD_STORAGE_DIR": temp_dir}
        ), patch.object(route, "current_user_id", return_value=user_id), patch.object(
            route, "require_member", return_value=None
        ):
            response = asyncio.run(route.upload_material_chunk(
                request=SlowChunkRequest(),
                intake_id=intake_id,
                file_id=file_id,
                offset=0,
                orm=orm,
            ))

        self.assertEqual(response.received_bytes, 5)
        self.assertTrue(orm.calls)

    def test_complete_direct_upload_submits_all_files_for_review_without_preview_step(self) -> None:
        route = _load_route()
        orm = _Orm(project_department_id="research-direct")
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        intake_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        file_id = uuid.UUID("00000000-0000-0000-0000-000000000041")
        storage_key = f"{project_id}/{intake_id}/{file_id}.md"
        orm.intake = SimpleNamespace(
            id=str(intake_id),
            project_id=str(project_id),
            department_id="research-direct",
            status="uploading",
            created_by_user_id=str(user_id),
        )
        orm.files = [SimpleNamespace(
            id=str(file_id), filename="README.md", format="md", size_bytes=5,
            content_hash="", raw_content=b"", extracted_text="", recommendation="keep",
            included=True, reason="direct", storage_key=storage_key, uploaded_bytes=5,
        )]

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"MATERIAL_UPLOAD_STORAGE_DIR": temp_dir}
        ), patch.object(route, "current_user_id", return_value=user_id), patch.object(
            route, "require_member", return_value=None
        ), patch.object(route, "record_audit", return_value=None), patch.object(
            route, "preview_materials", side_effect=AssertionError("AI preview must not run")
        ):
            route.append_chunk(storage_key, offset=0, chunk=b"hello")
            response = route.complete_material_upload_session(
                request=object(),
                intake_id=intake_id,
                orm=orm,
            )

        self.assertEqual(response.status, "pending_review")
        self.assertEqual(response.raw_document_count, 1)
        self.assertEqual(response.draft_id, uuid.UUID("00000000-0000-0000-0000-000000000050"))
        self.assertTrue(any("SET content_hash" in sql for sql, _ in orm.calls))
        self.assertTrue(any("SET status = 'pending_review'" in sql for sql, _ in orm.calls))

    def test_direct_uploaded_material_download_streams_from_persistent_storage(self) -> None:
        route = _load_route()
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        intake_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        file_id = uuid.UUID("00000000-0000-0000-0000-000000000041")
        storage_key = f"{project_id}/{intake_id}/{file_id}.pdf"

        def execute(statement, params=None):
            sql = str(statement)
            orm.calls.append((sql, params or {}))
            if "JOIN public.project_material_intakes" in sql:
                return _Result(SimpleNamespace(
                    filename="规范.pdf", raw_content=b"", storage_key=storage_key,
                    project_id=str(project_id),
                ))
            return _Result()

        orm.execute = execute
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {"MATERIAL_UPLOAD_STORAGE_DIR": temp_dir}
        ), patch.object(route, "current_user_id", return_value=user_id), patch.object(
            route, "require_member", return_value=None
        ):
            stored_path = Path(temp_dir) / storage_key
            stored_path.parent.mkdir(parents=True, exist_ok=True)
            stored_path.write_bytes(b"pdf-data")
            response = route.download_original_material(
                request=object(), intake_id=intake_id, file_id=file_id, orm=orm
            )

            self.assertEqual(Path(response.path), stored_path)

    def test_preview_rejects_stale_department_snapshot(self) -> None:
        route = _load_route()
        orm = _Orm(project_department_id="education-direct")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")

        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "require_member", return_value=None),
        ):
            with self.assertRaises(route.HTTPException) as raised:
                route.preview_project_materials(
                    request=object(),
                    project_id=project_id,
                    department_id="research-direct",
                    files=[],
                    orm=orm,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("project category changed", raised.exception.detail)
        self.assertFalse(
            any("INSERT INTO public.project_material_intakes" in sql for sql, _ in orm.calls)
        )

    def test_preview_uses_locked_current_project_department(self) -> None:
        route = _load_route()
        orm = _Orm(project_department_id="research-direct")

        with (
            patch.object(route, "current_user_id", return_value=uuid.uuid4()),
            patch.object(route, "require_member", return_value=None),
        ):
            with self.assertRaises(route.HTTPException):
                route.preview_project_materials(
                    request=object(),
                    project_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
                    department_id="research-direct",
                    files=[],
                    orm=orm,
                )

        project_sql = next(
            sql for sql, _ in orm.calls
            if "SELECT department_id" in sql and "FROM public.projects" in sql
        )
        self.assertIn("FOR SHARE", project_sql)

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
        ):
            response = route.preview_project_materials(
                request=object(),
                project_id=project_id,
                department_id="research",
                files=files,
                orm=orm,
            )

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

    def test_confirm_stages_only_safe_original_files_for_admin_review(self) -> None:
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
            SimpleNamespace(id=keep_id, filename="README.md", format="md", size_bytes=30, content_hash="hash-1", raw_content=b"# Project\n\nRun Docker", extracted_text="# Project\n\nRun Docker", recommendation="keep", included=True, reason="safe"),
            SimpleNamespace(id=secret_id, filename=".env.txt", format="txt", size_bytes=30, content_hash="hash-2", raw_content=b"TOKEN=secret", extracted_text="TOKEN=secret", recommendation="sensitive", included=False, reason="blocked"),
        ]
        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None),
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

        self.assertEqual(response.raw_document_count, 1)
        self.assertEqual(response.status, "pending_review")
        self.assertEqual(
            response.draft_id,
            uuid.UUID("00000000-0000-0000-0000-000000000050"),
        )
        self.assertFalse(hasattr(response, "curated_document_id"))
        draft_inserts = [
            params for sql, params in orm.calls
            if "INSERT INTO public.project_memory_drafts" in sql
        ]
        self.assertEqual(len(draft_inserts), 1)
        self.assertEqual(draft_inserts[0]["source_count"], 1)
        self.assertNotIn("curated_markdown", draft_inserts[0])
        self.assertNotIn("skills", draft_inserts[0])

    def test_cancel_preview_deletes_staged_payloads(self) -> None:
        route = _load_route()
        orm = _Orm()
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        intake_id = uuid.UUID("00000000-0000-0000-0000-000000000040")
        project_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
        orm.intake = SimpleNamespace(
            id=str(intake_id),
            project_id=str(project_id),
            status="preview_ready",
            created_by_user_id=str(user_id),
        )

        with (
            patch.object(route, "current_user_id", return_value=user_id),
            patch.object(route, "require_member", return_value=None),
            patch.object(route, "record_audit", return_value=None),
        ):
            response = route.cancel_project_materials(
                request=object(),
                intake_id=intake_id,
                orm=orm,
            )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(any("DELETE FROM public.project_material_intakes" in sql for sql, _ in orm.calls))


if __name__ == "__main__":
    unittest.main()
