from pathlib import Path


SCRIPT = Path(__file__).with_name("Test-PublicRelayMaterialApproval.ps1")


def test_material_approval_smoke_script_covers_full_permission_flow() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    required_contracts = (
        "/v4/knowledge/material-intakes/upload-sessions",
        "/v4/knowledge/material-intakes/upload-sessions/$intakeId/files/$fileId",
        "/v4/knowledge/material-intakes/upload-sessions/$intakeId/complete",
        "format-test-excel-r55.xlsx",
        "format-test-word-r55.docx",
        "format-test-powerpoint-r56.pptx",
        "format-test-pdf-r55.pdf",
        "direct-upload-r58.md",
        "direct upload did not retain five files",
        "AI sensitive scan must not run",
        "/v4/project-memory/drafts/$draftId/review",
        'expected HTTP 403',
        'hanshangbo@local.dev',
        'reviewed_by_user_id',
        'uploaded_by_user_id',
        'temporary_test_rows_remaining',
        '/auth/v1/admin/generate_link',
        '/auth/v1/verify',
        '/auth/v1/logout?scope=local',
    )

    for contract in required_contracts:
        assert contract in source


if __name__ == "__main__":
    test_material_approval_smoke_script_covers_full_permission_flow()
