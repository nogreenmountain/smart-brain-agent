from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


def _load_module():
    path = Path(__file__).parents[1] / "project_memory" / "storage.py"
    spec = importlib.util.spec_from_file_location("project_material_storage_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectMaterialStorageTests(unittest.TestCase):
    def test_chunks_are_appended_idempotently_and_hashed(self) -> None:
        storage = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"MATERIAL_UPLOAD_STORAGE_DIR": temp_dir}):
                key = storage.build_storage_key(
                    project_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
                    intake_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
                    file_id=uuid.UUID("00000000-0000-0000-0000-000000000030"),
                    filename="方案.pptx",
                )

                self.assertEqual(storage.append_chunk(key, offset=0, chunk=b"hello"), 5)
                self.assertEqual(storage.append_chunk(key, offset=5, chunk=b" world"), 11)
                self.assertEqual(storage.append_chunk(key, offset=0, chunk=b"hello"), 11)
                self.assertEqual(storage.file_size(key), 11)
                self.assertEqual(
                    storage.sha256_file(key),
                    "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
                )

    def test_chunk_offset_mismatch_does_not_corrupt_file(self) -> None:
        storage = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"MATERIAL_UPLOAD_STORAGE_DIR": temp_dir}):
                key = "project/intake/file.md"
                storage.append_chunk(key, offset=0, chunk=b"first")

                with self.assertRaises(storage.MaterialStorageConflict) as raised:
                    storage.append_chunk(key, offset=2, chunk=b"wrong")

                self.assertEqual(raised.exception.received_bytes, 5)
                self.assertEqual(storage.read_bytes(key), b"first")


if __name__ == "__main__":
    unittest.main()
