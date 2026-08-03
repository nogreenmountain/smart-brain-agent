from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path


def _load_module():
    path = Path(
        os.environ.get(
            "PROJECT_MEMORY_PUBLISH_PATH",
            Path(__file__).parents[1] / "project_memory" / "publish.py",
        )
    )
    spec = importlib.util.spec_from_file_location("project_memory_publish_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectMemoryPublishTests(unittest.TestCase):
    def test_build_skill_candidates_creates_traceable_procedure_pages(self) -> None:
        publish = _load_module()
        candidates = publish.build_skill_candidates(
            [
                {
                    "title": "Deploy locally",
                    "summary": "Start the verified local stack.",
                    "markdown_content": "# Deploy locally\n\n## Steps\n\n1. Start services",
                    "source_filenames": ["README.md"],
                },
                {
                    "title": "Verify API",
                    "summary": "Check the service after deployment.",
                    "markdown_content": "# Verify API\n\n## Steps\n\n1. Call health",
                    "source_filenames": ["ops.md"],
                },
            ],
            source_document_ids=["doc-1", "doc-2"],
        )

        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(candidate.page_type == "procedure" for candidate in candidates))
        self.assertEqual(candidates[0].source_ids, ["document:doc-1", "document:doc-2"])
        self.assertEqual(candidates[0].usefulness, 1.0)
        self.assertEqual(candidates[0].confidence, 1.0)

    def test_invalid_skill_payload_is_skipped(self) -> None:
        publish = _load_module()
        candidates = publish.build_skill_candidates(
            [{"title": "", "summary": "Missing title", "markdown_content": "text"}],
            source_document_ids=["doc-1"],
        )

        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
