from fastapi import APIRouter

from agentops.common.route_config import RouteConfig, register_routes
from agentops.auth.middleware import AuthenticatedRoute

from .metrics.views import ProjectMetricsView
from .traces.views import TraceListView, TraceDetailView
from .logs import LogsUploadView, get_trace_logs
from .objects import ObjectUploadView

from agentops.api.routes.v4.stripe_webhooks import router as stripe_webhooks_router
from .knowledge import router as knowledge_router
from .auth_me import router as auth_me_router
from .projects import router as projects_router
from .audit_admin import router as audit_admin_router
from .workday import router as workday_router
from .ai_chat import router as ai_chat_router
from .ai_monitor import router as ai_monitor_router
from .ai_usage import router as ai_usage_router
from .project_memory import router as project_memory_router

__all__ = ["router"]


router = APIRouter(prefix="/v4")


route_config: list[RouteConfig] = [
    # Metrics
    RouteConfig(
        name='get_project_metrics',
        path="/meterics/project/{project_id}",
        endpoint=ProjectMetricsView,
        methods=["GET"],
    ),
    # Traces
    RouteConfig(
        name='get_project_traces',
        path="/traces/list/{project_id}",
        endpoint=TraceListView,
        methods=["GET"],
    ),
    RouteConfig(
        name='get_trace',
        path="/traces/detail/{trace_id}",
        endpoint=TraceDetailView,
        methods=["GET"],
    ),
    # Objects
    RouteConfig(
        name='upload_object',
        path="/objects/upload/",
        endpoint=ObjectUploadView,
        methods=["POST"],
    ),
    # Logs
    RouteConfig(
        name='upload_logs',
        path="/logs/upload/",
        endpoint=LogsUploadView,
        methods=["POST"],
    ),
    RouteConfig(
        name='get_trace_logs',
        path="/logs/{trace_id}",
        endpoint=get_trace_logs,
        methods=["GET"],
    ),
]

api_router = APIRouter(route_class=AuthenticatedRoute)
register_routes(api_router, route_config, prefix="/v4")
router.include_router(api_router)

router.include_router(stripe_webhooks_router)
router.include_router(knowledge_router)
router.include_router(auth_me_router)
router.include_router(projects_router)
router.include_router(audit_admin_router)
router.include_router(workday_router)
router.include_router(ai_chat_router)
router.include_router(ai_monitor_router)
router.include_router(ai_usage_router)
router.include_router(project_memory_router)
