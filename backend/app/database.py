from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session


DATABASE_FILE = Path(__file__).parent.parent / "data" / "personal_workbench.db"
DATABASE_FILE.parent.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATABASE_FILE.as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if dbapi_connection.__class__.__module__ == "sqlite3":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    with Session(engine) as session:
        yield session
