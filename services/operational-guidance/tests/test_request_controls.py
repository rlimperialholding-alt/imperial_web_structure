from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.observability import RequestSizeLimitMiddleware


def test_request_size_limit_checks_actual_body() -> None:
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=16)

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    client = TestClient(app)
    assert client.post("/echo", content=b"1234567890").status_code == 200
    response = client.post("/echo", content=b"x" * 32)
    assert response.status_code == 413
    assert response.json()["detail"] == "Request body too large"
