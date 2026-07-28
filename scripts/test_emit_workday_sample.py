from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from emit_workday_sample import build_payload


class WorkdaySampleTests(unittest.TestCase):
    def test_sample_timestamps_fall_inside_requested_shanghai_business_day(self) -> None:
        work_date = date(2020, 1, 2)
        payload = build_payload(
            project_id="project-1",
            employee_id="employee-001",
            employee_name="Alice",
            work_date=work_date,
        )

        spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
        starts = [
            datetime.fromtimestamp(
                int(span["startTimeUnixNano"]) / 1_000_000_000,
                tz=timezone.utc,
            )
            for span in spans
        ]
        shanghai = timezone(timedelta(hours=8))
        day_start = datetime.combine(work_date, time.min, tzinfo=shanghai)
        day_end = day_start + timedelta(days=1)

        self.assertTrue(
            all(day_start <= timestamp.astimezone(shanghai) < day_end for timestamp in starts)
        )


if __name__ == "__main__":
    unittest.main()
