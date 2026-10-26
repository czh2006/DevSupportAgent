from collections.abc import Generator
from hashlib import sha256

from sqlalchemy import create_engine, event, inspect, text
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


def migrate_legacy_agent_run_keys(
    db_engine=engine,
) -> None:
    if db_engine.dialect.name != "sqlite":
        raise RuntimeError(
            "The local schema migration currently supports SQLite only."
        )

    with db_engine.begin() as connection:
        if "agent_run_keys" not in inspect(connection).get_table_names():
            return

        columns = {
            column["name"]
            for column in inspect(connection).get_columns("agent_run_keys")
        }
        renamed_legacy_key = "key" in columns and "key_hash" not in columns

        if renamed_legacy_key:
            connection.exec_driver_sql(
                'ALTER TABLE agent_run_keys RENAME COLUMN "key" TO key_hash'
            )
            columns.remove("key")
            columns.add("key_hash")

        if "key_hash" not in columns:
            raise RuntimeError(
                "agent_run_keys has no recognized key column."
            )

        if "created_at" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE agent_run_keys "
                "ADD COLUMN created_at DATETIME NOT NULL "
                "DEFAULT '1970-01-01 00:00:00'"
            )

        if renamed_legacy_key:
            rows = connection.exec_driver_sql(
                "SELECT session_id, key_hash FROM agent_run_keys"
            ).all()
            for session_id, old_key in rows:
                hashed_key = sha256(old_key.encode("utf-8")).hexdigest()
                connection.execute(
                    text(
                        "UPDATE agent_run_keys "
                        "SET key_hash = :hashed_key "
                        "WHERE session_id = :session_id AND key_hash = :old_key"
                    ),
                    {
                        "hashed_key": hashed_key,
                        "session_id": session_id,
                        "old_key": old_key,
                    },
                )


def get_db() -> Generator[Session, None, None]:
    with SessionFactory() as db_session:
        yield db_session
