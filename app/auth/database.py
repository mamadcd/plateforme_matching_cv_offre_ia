from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = (
    create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    if settings.DATABASE_URL
    else None
)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False) if engine else None


def initialize_database() -> None:
    if engine is None:
        return

    from app.auth import models  # noqa: F401
    from app.workflows import models as workflow_models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db_session() -> Generator[Session, None, None]:
    if SessionFactory is None:
        raise HTTPException(status_code=503, detail="La base PostgreSQL n'est pas configurée")

    with SessionFactory() as session:
        yield session


def get_optional_db_session() -> Generator[Session | None, None, None]:
    if SessionFactory is None:
        yield None
        return

    with SessionFactory() as session:
        yield session