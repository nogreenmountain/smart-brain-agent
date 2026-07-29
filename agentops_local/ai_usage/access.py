from __future__ import annotations

from datetime import date


class UsageAccessError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def resolve_employee_scope(
    *,
    is_admin: bool,
    own_employee_id: str,
    requested_employee_id: str | None,
) -> str:
    requested = (requested_employee_id or "").strip()
    if is_admin:
        if not requested:
            raise UsageAccessError(422, "employee_id is required for admin queries")
        return requested
    if requested and requested != own_employee_id:
        raise UsageAccessError(
            403,
            "regular users can only view their own AI usage records",
        )
    return own_employee_id


def validate_date_range(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        raise UsageAccessError(422, "end_date must not be earlier than start_date")
    period_days = (end_date - start_date).days + 1
    if period_days > 366:
        raise UsageAccessError(422, "date range cannot exceed 366 days")
    return period_days
