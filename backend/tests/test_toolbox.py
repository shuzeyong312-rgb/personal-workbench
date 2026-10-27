import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ToolboxItem


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(ToolboxItem(kind="builtin", builtin_key="compress", name="图片压缩", name_key="图片压缩", category="图片", description="", favorite=True))
        db.commit()
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    client = TestClient(app)
    yield client
    client.close()
    app.dependency_overrides.clear()
    engine.dispose()


def test_crud_and_uniqueness(client):
    assert client.delete("/api/toolbox/sites/1").status_code == 403
    payload = {"name": " Straße ", "url": "HTTPS://Example.com:443/Path", "category": "PDF", "description": ""}
    response = client.post("/api/toolbox/sites", json=payload)
    assert response.status_code == 201
    item = response.json()
    assert item["url"] == "https://example.com/Path"
    assert client.post("/api/toolbox/sites", json={**payload, "name": "STRASSE", "url": "https://other.test"}).json()["code"] == "duplicate_name"
    assert client.post("/api/toolbox/sites", json={**payload, "name": "other"}).json()["code"] == "duplicate_url"
    assert client.post("/api/toolbox/sites", json={**payload, "name": "other", "url": "https://example.com/a/../Path"}).json()["code"] == "duplicate_url"
    assert client.post("/api/toolbox/sites", json={**payload, "name": "other", "url": "https://example.com/%2e%2e/Path"}).json()["code"] == "duplicate_url"
    assert client.post("/api/toolbox/sites", json={**payload, "name": "port zero", "url": "https://example.com:0/Path"}).status_code == 201
    assert client.post("/api/toolbox/sites", json={**payload, "name": "other", "url": "https://example.com/path"}).status_code == 201
    assert client.patch(f"/api/toolbox/items/{item['id']}/favorite", json={"favorite": True}).json()["favorite"] is True
    assert client.patch(f"/api/toolbox/sites/{item['id']}", json={**payload, "name": "changed"}).status_code == 200
    assert client.delete(f"/api/toolbox/sites/{item['id']}").status_code == 204
    assert client.get("/api/toolbox/items").status_code == 200


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///tmp/a", "https://u:p@example.com", "https://example.com/a b", "https://example.com:99999/"])
def test_rejects_bad_url(client, url):
    response = client.post("/api/toolbox/sites", json={"name": "test", "url": url})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_url"


def test_missing_catalog_has_actionable_error():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    def override():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        response = TestClient(app).get("/api/toolbox/items")
        assert response.status_code == 503
        assert response.json()["code"] == "toolbox_migration_required"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
