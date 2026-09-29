"""Optional SQLAlchemy session manager for relational business models."""

import os
import logging
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL") or (
    f"sqlite:///{Path(__file__).resolve().parents[1] / 'local_orm.sqlite'}"
)

engine_options = {"pool_pre_ping": True, "echo": False}
if not DATABASE_URL.startswith("sqlite:"):
    engine_options.update(pool_size=10, max_overflow=20)
engine = create_engine(
    DATABASE_URL,
    **engine_options,
)
logger.info("Optional ORM database backend: %s", engine.url.get_backend_name())

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Session:
    """Yield a database session and close it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Session:
    """Commit a session on success or roll it back on failure."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Register the ORM models and create their tables."""
    try:
        from database import models  # noqa: F401

        Base.metadata.create_all(bind=engine)
        logger.info("Optional ORM tables initialized")
    except Exception as e:
        logger.error("ORM table initialization failed: %s", e)
        raise


def drop_db():
    """Drop the optional ORM tables for local development or tests."""
    try:
        Base.metadata.drop_all(bind=engine)
        logger.info("Optional ORM tables removed")
    except Exception as e:
        logger.error("ORM table removal failed: %s", e)
        raise
