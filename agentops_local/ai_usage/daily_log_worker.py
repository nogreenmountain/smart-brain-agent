from __future__ import annotations

import os
import logging
import time
from datetime import date, datetime, time as clock_time, timedelta, timezone


TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
logger = logging.getLogger(__name__)


def _schedule_time() -> clock_time:
    hour = min(max(int(os.getenv("AI_WORKLOG_RUN_HOUR", "20")), 0), 23)
    minute = min(max(int(os.getenv("AI_WORKLOG_RUN_MINUTE", "0")), 0), 59)
    return clock_time(hour=hour, minute=minute)


def latest_due_date(now: datetime) -> date:
    local_now = now.astimezone(TIMEZONE)
    if local_now.time() >= _schedule_time():
        return local_now.date()
    return local_now.date() - timedelta(days=1)


def next_run_at(now: datetime) -> datetime:
    local_now = now.astimezone(TIMEZONE)
    scheduled = datetime.combine(local_now.date(), _schedule_time(), tzinfo=TIMEZONE)
    if local_now >= scheduled:
        scheduled += timedelta(days=1)
    return scheduled


def sleep_seconds_after_run(
    now: datetime,
    *,
    failure_count: int,
    retry_seconds: int,
) -> int:
    if failure_count > 0:
        return max(retry_seconds, 60)
    return max(int((next_run_at(now) - now.astimezone(TIMEZONE)).total_seconds()), 1)


def main() -> None:
    from agentops.ai_usage.daily_log_service import generate_daily_worklogs
    from agentops.common.orm import get_orm_session

    logging.basicConfig(level=os.getenv("LOGGING_LEVEL", "INFO"))
    retry_seconds = int(os.getenv("AI_WORKLOG_RETRY_SECONDS", "900"))
    due_date = latest_due_date(datetime.now(TIMEZONE))
    while True:
        session_generator = get_orm_session()
        orm = next(session_generator)
        try:
            result = generate_daily_worklogs(orm, work_date=due_date)
            logger.info(
                "AI daily worklog run: date=%s employees=%s ready=%s empty=%s skipped=%s failed=%s",
                due_date,
                result.employee_count,
                result.ready_count,
                result.empty_count,
                result.skipped_count,
                result.failure_count,
            )
        finally:
            session_generator.close()

        now = datetime.now(TIMEZONE)
        delay = sleep_seconds_after_run(
            now,
            failure_count=result.failure_count,
            retry_seconds=retry_seconds,
        )
        time.sleep(delay)
        if result.failure_count == 0:
            due_date = next_run_at(now).date()


if __name__ == "__main__":
    main()
