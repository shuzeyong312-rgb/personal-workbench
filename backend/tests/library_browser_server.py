"""Isolated browser QA server: temporary database, no production app lifespan."""
import argparse
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import get_db
from scripts.rehearse_library_identity_v2 import facts, migrate
from app.main import http_exception_handler
from fastapi import HTTPException
from app.models import LibraryProduct
from app.product_library import router
from app.product_library_service import now


def main(port=8217):
    with tempfile.TemporaryDirectory(prefix="library-browser-") as directory:
        engine = create_engine(f"sqlite:///{Path(directory).as_posix()}/qa.db", connect_args={"check_same_thread": False})
        db_path = Path(directory) / "qa.db"
        migrate(db_path, "20261018_16")
        with Session(engine) as db:
            for index in range(1, 46):
                db.add(LibraryProduct(manufacturer_name="隔离验收厂家", model=f"QA-{index:03}", name=f"验收灯 {index}", parameters="3.7V，客户参数", selling_points="便携", wholesale_price_cents=1001 + index, price_note="PRIVATE_INTERNAL_NOTE", version=1, created_at=now(), updated_at=now()))
            db.commit()
        before = facts(db_path)
        migrate(db_path, "20261020_17")
        assert facts(db_path)["tables"] == before["tables"], "Browser fixture migration changed existing rows"
        app = FastAPI()
        app.include_router(router)
        app.add_exception_handler(HTTPException, http_exception_handler)
        def session():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        try:
            uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
        finally:
            engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8217)
    main(parser.parse_args().port)
