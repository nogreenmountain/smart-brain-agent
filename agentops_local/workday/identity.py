from __future__ import annotations

import re
import uuid

from employee_telemetry.bundle import EMPLOYEE_ID_PATTERN


def derive_employee_identity(
    *,
    user_id: uuid.UUID,
    email: str,
    full_name: str | None,
) -> tuple[str, str]:
    local_part = email.partition("@")[0].strip().lower()
    employee_id = (
        local_part
        if EMPLOYEE_ID_PATTERN.fullmatch(local_part)
        else f"user-{user_id}"
    )
    candidate_name = (full_name or local_part or employee_id).strip()
    employee_name = re.sub(r"[\x00-\x1f\x7f]+", " ", candidate_name)
    employee_name = " ".join(employee_name.split())[:80] or employee_id
    return employee_id, employee_name
