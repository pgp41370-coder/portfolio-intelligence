from fastapi.testclient import TestClient


def test_api_v1_reports_running(client: TestClient) -> None:
    response = client.get("/api/v1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "name": "Portfolio Intelligence API",
        "version": "v1",
        "status": "running",
        "message": "Portfolio Intelligence API is running",
    }
