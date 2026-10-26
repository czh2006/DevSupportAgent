from datetime import datetime
from hashlib import sha256
import json

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.agent.runner import AgentResult
from app.services.agent_run_service import AgentRunService
from app.storage.database import Base, migrate_legacy_agent_run_keys
from app.storage.models import AgentRun, TroubleshootingSession


def test_migrates_legacy_agent_run_keys_and_preserves_replay():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE agent_run_keys (
                    session_id VARCHAR(36) NOT NULL,
                    "key" VARCHAR(128) NOT NULL,
                    fingerprint VARCHAR(64) NOT NULL,
                    run_id VARCHAR(36) NOT NULL,
                    PRIMARY KEY (session_id, "key"),
                    UNIQUE (run_id)
                )
                """
            )

        Base.metadata.create_all(bind=engine)

        session_id = "legacy-session"
        run_id = "legacy-run"
        raw_key = "legacy-retry-key"
        question = "Original question"
        fingerprint = sha256(json.dumps(
            {
                "question": question,
                "request_id": None,
                "environment": None,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

        with Session(engine) as db:
            db.add(TroubleshootingSession(
                id=session_id,
                title="Legacy run",
                problem_description="Test schema upgrade",
            ))
            db.add(AgentRun(
                id=run_id,
                session_id=session_id,
                execution_status="completed",
                question=question,
                request_id=None,
                environment=None,
                result_json=AgentResult(
                    status="answered",
                    answer="Previously completed.",
                ).model_dump_json(),
                error_code=None,
                duration_ms=1,
                created_at=datetime.now(),
                finished_at=datetime.now(),
            ))
            db.flush()
            db.execute(text(
                'INSERT INTO agent_run_keys '
                '(session_id, "key", fingerprint, run_id) '
                'VALUES (:session_id, :raw_key, :fingerprint, :run_id)'
            ), {
                "session_id": session_id,
                "raw_key": raw_key,
                "fingerprint": fingerprint,
                "run_id": run_id,
            })
            db.commit()

        migrate_legacy_agent_run_keys(engine)

        columns = {
            column["name"]
            for column in inspect(engine).get_columns("agent_run_keys")
        }
        assert "key_hash" in columns
        assert "created_at" in columns
        assert "key" not in columns

        expected_key_hash = sha256(raw_key.encode("utf-8")).hexdigest()
        with Session(engine) as db:
            stored_hash = db.scalar(text(
                "SELECT key_hash FROM agent_run_keys "
                "WHERE session_id = :session_id"
            ), {"session_id": session_id})
            assert stored_hash == expected_key_hash

            replay = AgentRunService(db).reserve(
                session_id,
                question,
                None,
                None,
                raw_key,
            )

        assert replay.created is False
        assert replay.run.id == run_id
        assert replay.run.result is not None
        assert replay.run.result.answer == "Previously completed."
    finally:
        engine.dispose()
