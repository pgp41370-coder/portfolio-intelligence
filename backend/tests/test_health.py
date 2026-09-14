from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200


def test_health_reports_status_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.json() == {"status": "ok"}
