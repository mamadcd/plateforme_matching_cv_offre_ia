from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('candidate', 'recruiter', 'admin')", name="ck_users_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class AnonymousMatchUse(Base):
    __tablename__ = "anonymous_match_uses"

    ip_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)