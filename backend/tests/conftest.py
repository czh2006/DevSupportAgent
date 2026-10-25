from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.storage.database import Base, get_db

from app.extraction.context_extractor import RuleContextExtractor
from app.extraction.pipeline import get_context_extractor


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestSessionFactory = sessionmaker(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db() -> Generator[Session, None, None]:
        with TestSessionFactory() as db_session:
            yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_context_extractor] = (
        RuleContextExtractor
    )

    test_client = TestClient(app)

    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()
        test_engine.dispose()