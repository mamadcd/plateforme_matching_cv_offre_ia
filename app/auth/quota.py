from datetime import date
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.auth.models import AnonymousMatchUse
from app.core.config import settings


ANONYMOUS_MATCH_DAILY_LIMIT = 3


def consume_anonymous_match(session: Session, client_ip: str) -> None:
    secret = settings.AUTH_SECRET_KEY
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Le matching visiteur n'est pas configuré")

    today = date.today()
    ip_digest = sha256(f"{secret}:{client_ip}".encode("utf-8")).hexdigest()
    session.execute(
        delete(AnonymousMatchUse).where(AnonymousMatchUse.usage_date < today)
    )
    dialect = session.get_bind().dialect.name
    insert = sqlite_insert if dialect == "sqlite" else postgres_insert
    statement = (
        insert(AnonymousMatchUse)
        .values(ip_digest=ip_digest, usage_date=today, request_count=1)
        .on_conflict_do_update(
            index_elements=["ip_digest", "usage_date"],
            set_={"request_count": AnonymousMatchUse.request_count + 1},
            where=AnonymousMatchUse.request_count < ANONYMOUS_MATCH_DAILY_LIMIT,
        )
        .returning(AnonymousMatchUse.request_count)
    )
    consumed = session.scalar(statement)
    session.commit()
    if consumed is None:
        raise HTTPException(status_code=429, detail="Quota visiteur atteint : 3 analyses par jour")