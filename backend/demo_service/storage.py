from pathlib import Path

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)


metadata = MetaData()

request_logs = Table(
    "service_request_logs",
    metadata,
    Column(
        "request_id",
        String(36),
        primary_key=True,
    ),
    Column(
        "project_id",
        String(64),
        nullable=False,
        index=True,
    ),
    Column("service", String(64), nullable=False),
    Column("environment", String(32), nullable=False),
    Column("method", String(10), nullable=False),
    Column("route", String(128), nullable=False),
    Column("http_status_code", Integer, nullable=False),
    Column("duration_ms", Float, nullable=False),
    Column("error_code", String(64)),
    Column("upstream_status_code", Integer),
    Column("retry_after_seconds", Integer),
    Column("created_at", String(40), nullable=False),
    Column("source", String(32), nullable=False),
)


class LogStore:
    def __init__(self, path: Path):
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={
                "check_same_thread": False,
                "timeout": 3,
            },
        )

        metadata.create_all(self.engine)

    def write(self, record: dict) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                request_logs.insert(),
                record,
            )

    def get(
        self,
        project_id: str,
        request_id: str,
    ) -> dict | None:
        statement = select(request_logs).where(
            request_logs.c.project_id == project_id,
            request_logs.c.request_id == request_id,
        )

        with self.engine.connect() as connection:
            row = (
                connection.execute(statement)
                .mappings()
                .first()
            )

            return dict(row) if row is not None else None

    def close(self) -> None:
        self.engine.dispose()