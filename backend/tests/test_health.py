from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models import Base


def test_health_returns_ok() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app.state.collection_session_factory = sessionmaker(bind=engine)
    try:
        with TestClient(app) as client:
            response = client.get("/api/health")
    finally:
        app.state.collection_session_factory = None
        engine.dispose()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
