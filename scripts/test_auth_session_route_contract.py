from pathlib import Path


AUTH_APP = Path(__file__).parents[1] / "api" / "agentops" / "auth" / "app.py"
API_DOCKERFILE = Path(__file__).parents[1] / "Dockerfile.api-workday"


def test_auth_session_view_is_registered() -> None:
    source = AUTH_APP.read_text(encoding="utf-8")

    assert "auth_session," in source
    assert "name='auth_session'" in source
    assert 'path="/session"' in source
    assert "endpoint=auth_session" in source

    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")
    assert (
        "COPY api/agentops/auth/app.py /app/agentops/auth/app.py"
        in dockerfile
    )


if __name__ == "__main__":
    test_auth_session_view_is_registered()
