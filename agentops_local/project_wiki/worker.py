from __future__ import annotations

import importlib.util
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

try:
    from sqlalchemy import text
except ModuleNotFoundError:
    def text(value: str) -> str:
        return value

try:
    from agentops.project_wiki.service import compile_project_wiki
except ModuleNotFoundError:
    path = Path(__file__).with_name("service.py")
    spec = importlib.util.spec_from_file_location("project_wiki_service_for_worker", path)
    if spec is None or spec.loader is None:
        raise
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    compile_project_wiki = module.compile_project_wiki


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerRunResult:
    project_count: int
    success_count: int
    failure_count: int


def run_once(orm) -> WorkerRunResult:
    projects = orm.execute(
        text("""
            SELECT id::text, name
            FROM public.projects
            WHERE completed_at IS NULL
            ORDER BY created_at ASC
        """)
    ).all()
    success_count = 0
    failure_count = 0
    for project in projects:
        project_id = uuid.UUID(str(project.id))
        try:
            compile_project_wiki(
                orm,
                project_id=project_id,
                project_name=str(project.name),
                triggered_by_user_id=None,
            )
            success_count += 1
        except Exception:
            failure_count += 1
            try:
                orm.rollback()
            except Exception:
                pass
            logger.exception("Scheduled project Wiki compile failed for %s", project_id)
    return WorkerRunResult(
        project_count=len(projects),
        success_count=success_count,
        failure_count=failure_count,
    )


def main() -> None:
    from agentops.common.orm import get_orm_session

    logging.basicConfig(level=os.getenv("LOGGING_LEVEL", "INFO"))
    initial_delay = max(0, int(os.getenv("PROJECT_WIKI_INITIAL_DELAY_SECONDS", "60")))
    interval = max(300, int(os.getenv("PROJECT_WIKI_INTERVAL_SECONDS", "86400")))
    if initial_delay:
        time.sleep(initial_delay)
    while True:
        session_generator = get_orm_session()
        orm = next(session_generator)
        try:
            result = run_once(orm)
            logger.info(
                "Project Wiki scheduled run: projects=%s success=%s failed=%s",
                result.project_count,
                result.success_count,
                result.failure_count,
            )
        finally:
            session_generator.close()
        time.sleep(interval)


if __name__ == "__main__":
    main()
