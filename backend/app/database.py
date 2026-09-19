from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase


DATABASE_FILE = Path(__file__).parent.parent / "data" / "personal_workbench.db"
DATABASE_FILE.parent.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATABASE_FILE.as_posix()}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass
