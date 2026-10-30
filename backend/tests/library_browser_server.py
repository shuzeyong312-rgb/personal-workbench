"""Isolated browser QA server: temporary database, no production app lifespan."""
import argparse
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import get_db
from scripts.rehearse_library_identity_v2 import facts, migrate
from app.main import http_exception_handler
from fastapi import HTTPException
from app.product_library import router
from app.product_library_service import now


def main(port=8217):
    with tempfile.TemporaryDirectory(prefix="library-browser-") as directory:
        engine = create_engine(f"sqlite:///{Path(directory).as_posix()}/qa.db", connect_args={"check_same_thread": False})
        db_path = Path(directory) / "qa.db"
        migrate(db_path, "20261018_16")
        with engine.begin() as connection:
            for index in range(1,46):
                connection.execute(text("""INSERT INTO library_products(manufacturer_name,model,name,parameters,selling_points,wholesale_price_cents,price_note,version,created_at,updated_at)
                    VALUES ('隔离验收厂家',:model,:name,'3.7V，客户参数','便携',:price,'PRIVATE_INTERNAL_NOTE',1,:stamp,:stamp)"""),dict(model=f'QA-{index:03}',name=f'验收灯 {index}',price=1001+index,stamp=now()))
            before=connection.exec_driver_sql('SELECT id,model,name,wholesale_price_cents,version FROM library_products ORDER BY id').all()
        migrate(db_path, '20261030_22')
        with engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT id,model,name,wholesale_price_cents,version FROM library_products ORDER BY id').all()==before
        assert facts(db_path)['foreign_key_violations']==0
        app = FastAPI()
        app.include_router(router)
        app.add_exception_handler(HTTPException, http_exception_handler)
        app.mount('/', StaticFiles(directory=Path(__file__).parents[2] / 'frontend' / 'dist', html=True), name='frontend')
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
