import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./mensch.db"


class Base(DeclarativeBase):
    pass


def make_sessionmaker(database_url: str | None = None):
    url = database_url or os.environ.get("MENSCH_DATABASE_URL", DEFAULT_DATABASE_URL)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
