from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{settings.database_path.as_posix()}",
    connect_args={"check_same_thread": False},
)

@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()

    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()

SessionFactory = sessionmaker(bind=engine)


def get_db() -> Generator[Session, None, None]:
    with SessionFactory() as db_session:
        yield db_session