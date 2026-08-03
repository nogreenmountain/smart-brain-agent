from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load_module():
    path = Path(
        os.environ.get(
            "PROJECT_MATERIAL_INTAKE_PATH",
            Path(__file__).parents[1] / "project_memory" / "intake.py",
        )
    )
    spec = importlib.util.spec_from_file_location("project_material_intake_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ProjectMaterialIntakeTests(unittest.TestCase):
    def test_batch_limits_reject_oversized_file_and_batch(self) -> None:
        intake = _load_module()

        with self.assertRaisesRegex(ValueError, "single file"):
            intake.validate_batch_limits([("large.pdf", 21 * 1024 * 1024)])

        with self.assertRaisesRegex(ValueError, "batch"):
            intake.validate_batch_limits(
                [("one.pdf", 20 * 1024 * 1024), ("two.pdf", 20 * 1024 * 1024), ("three.pdf", 11 * 1024 * 1024)]
            )

    def test_confirmation_never_allows_hard_blocked_files(self) -> None:
        intake = _load_module()
        files = [
            SimpleNamespace(id="keep", recommendation="keep", included=True),
            SimpleNamespace(id="review", recommendation="review", included=True),
            SimpleNamespace(id="secret", recommendation="sensitive", included=False),
            SimpleNamespace(id="duplicate", recommendation="duplicate", included=False),
            SimpleNamespace(id="log", recommendation="low_value", included=False),
        ]

        selected = intake.select_confirmed_files(
            files,
            requested_ids={"keep", "review", "secret", "duplicate", "log"},
        )

        self.assertEqual([row.id for row in selected], ["keep", "review"])

    def test_review_markdown_contains_curated_source_and_every_skill(self) -> None:
        intake = _load_module()
        skills = [
            SimpleNamespace(title="Deploy locally", markdown_content="# Deploy locally\n\n1. Start services"),
            SimpleNamespace(title="Verify API", markdown_content="# Verify API\n\n1. Call health"),
        ]

        markdown = intake.build_review_markdown(
            project_name="Smart Brain",
            curated_markdown="# Source\n\nUse Docker.",
            skills=skills,
        )

        self.assertIn("## 整理后的项目资料", markdown)
        self.assertIn("## 可复用 Skill", markdown)
        self.assertIn("Deploy locally", markdown)
        self.assertIn("Verify API", markdown)


if __name__ == "__main__":
    unittest.main()
