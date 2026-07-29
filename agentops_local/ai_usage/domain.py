from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class UsageMessage:
    role: str
    content: str
    token_count: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class UsageRecord:
    id: str
    record_type: str
    project_id: str
    project_name: str
    employee_id: str
    employee_name: str
    source: str
    title: str
    started_at: datetime
    ended_at: datetime | None = None
    task_id: str = "unassigned"
    task_title: str | None = None
    model: str | None = None
    status: str = "ok"
    duration_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    error_count: int = 0
    trace_id: str | None = None
    message_count: int = 0
    messages: tuple[UsageMessage, ...] | None = None

    @property
    def effective_total_tokens(self) -> int:
        return self.total_tokens or self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class DailyUsage:
    date: date
    record_count: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error_count: int = 0


@dataclass(frozen=True)
class HourlyUsage:
    hour: int
    record_count: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class SourceUsage:
    source: str
    record_count: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class UsageSummary:
    start_date: date
    end_date: date
    period_days: int
    active_days: int
    record_count: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    average_tokens_per_day: float
    error_count: int
    total_cost: float
    daily_usage: tuple[DailyUsage, ...] = field(default_factory=tuple)
    hourly_usage: tuple[HourlyUsage, ...] = field(default_factory=tuple)
    source_usage: tuple[SourceUsage, ...] = field(default_factory=tuple)


def _local_day(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI_TIMEZONE)
    return value.astimezone(SHANGHAI_TIMEZONE).date()


def _local_hour(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI_TIMEZONE)
    return value.astimezone(SHANGHAI_TIMEZONE).hour


def build_usage_summary(
    records: list[UsageRecord],
    *,
    start_date: date,
    end_date: date,
) -> UsageSummary:
    if end_date < start_date:
        raise ValueError("end_date must not be earlier than start_date")

    period_days = (end_date - start_date).days + 1
    days = [start_date + timedelta(days=index) for index in range(period_days)]
    daily = {
        item: {
            "record_count": 0,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "error_count": 0,
        }
        for item in days
    }
    hourly = {
        hour: {"record_count": 0, "total_tokens": 0}
        for hour in range(24)
    }
    sources: dict[str, dict[str, int]] = {}

    for record in records:
        local_day = _local_day(record.started_at)
        if local_day not in daily:
            continue
        tokens = record.effective_total_tokens
        day_bucket = daily[local_day]
        day_bucket["record_count"] += 1
        day_bucket["total_tokens"] += tokens
        day_bucket["prompt_tokens"] += record.prompt_tokens
        day_bucket["completion_tokens"] += record.completion_tokens
        day_bucket["error_count"] += record.error_count

        hour_bucket = hourly[_local_hour(record.started_at)]
        hour_bucket["record_count"] += 1
        hour_bucket["total_tokens"] += tokens

        source_bucket = sources.setdefault(
            record.source,
            {"record_count": 0, "total_tokens": 0},
        )
        source_bucket["record_count"] += 1
        source_bucket["total_tokens"] += tokens

    total_tokens = sum(item["total_tokens"] for item in daily.values())
    return UsageSummary(
        start_date=start_date,
        end_date=end_date,
        period_days=period_days,
        active_days=sum(item["record_count"] > 0 for item in daily.values()),
        record_count=sum(item["record_count"] for item in daily.values()),
        total_tokens=total_tokens,
        prompt_tokens=sum(item["prompt_tokens"] for item in daily.values()),
        completion_tokens=sum(item["completion_tokens"] for item in daily.values()),
        average_tokens_per_day=round(total_tokens / period_days, 2),
        error_count=sum(item["error_count"] for item in daily.values()),
        total_cost=round(sum(record.cost for record in records), 9),
        daily_usage=tuple(
            DailyUsage(date=item, **daily[item])
            for item in days
        ),
        hourly_usage=tuple(
            HourlyUsage(hour=hour, **hourly[hour])
            for hour in range(24)
        ),
        source_usage=tuple(
            SourceUsage(source=source, **values)
            for source, values in sorted(
                sources.items(),
                key=lambda item: (-item[1]["total_tokens"], item[0]),
            )
        ),
    )
