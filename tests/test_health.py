"""API health endpoint tests."""

from fastapi.testclient import TestClient

from app.agent.provider import FakeScreeningProvider
from app.main import create_app


def test_health_endpoint() -> None:
    """The health endpoint reports a successful process status."""

    application = create_app(screening_provider=FakeScreeningProvider([]))
    response = TestClient(application).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_groups_operational_workflows() -> None:
    """Local API docs expose stable workflow-oriented tags."""

    schema = create_app(screening_provider=FakeScreeningProvider([])).openapi()

    assert [tag["name"] for tag in schema["tags"]] == [
        "ATS",
        "Conversations",
        "Voice",
        "Operations",
        "Recruiter",
    ]
    assert schema["paths"]["/api/ats/applications"]["post"]["tags"] == ["ATS"]
    start = schema["paths"]["/api/conversations/{conversation_id}/start"]
    assert start["post"]["tags"] == ["Conversations"]
    assert schema["paths"]["/health"]["get"]["tags"] == ["Operations"]
    recruiter = schema["paths"]["/api/recruiter/applications"]
    assert recruiter["get"]["tags"] == ["Recruiter"]
    voice = schema["paths"]["/api/voice/conversations/{conversation_id}/turn"]
    assert voice["post"]["tags"] == ["Voice"]
