from collections.abc import Callable

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import text

from agentops.common.orm import session_scope

from .environment import AUTH_COOKIE_NAME, AUTH_EXTEND_SESSIONS
from .exceptions import AuthException
from .session import Session
from .views import _decode_session_cookie


def _require_active_team_member(session: Session) -> None:
    """Reject and expire cached sessions after a team member is disabled."""
    with session_scope() as orm:
        row = orm.execute(
            text("""
                SELECT COALESCE(is_active, true) AS is_active
                FROM public.users
                WHERE id = :user_id
            """),
            {"user_id": str(session.user_id)},
        ).first()
    if row is not None and not bool(row.is_active):
        session.expire()
        raise AuthException("Team member account is disabled.")


class AuthenticatedRoute(APIRoute):
    """Authenticated API route with immediate team-member deactivation checks."""

    def _get_session(self, request: Request) -> Session:
        if not (cookie := request.cookies.get(AUTH_COOKIE_NAME)):
            raise AuthException("User is not authenticated.")

        if not (session := _decode_session_cookie(cookie)):
            raise AuthException("User's session has expired.")

        _require_active_team_member(session)

        if AUTH_EXTEND_SESSIONS:
            session.extend()

        return session

    def get_route_handler(self) -> Callable:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            try:
                request.state.session = self._get_session(request)
            except AuthException as exc:
                if not getattr(self.endpoint, "is_public", False):
                    raise exc

            return await original_route_handler(request)

        return custom_route_handler
