from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.database import get_db_session
from app.auth.models import User
from app.auth.routes import require_roles
from app.auth.schemas import AdminUserResponse, AdminUserUpdate
from app.core.config import settings
from app.workflows.models import Application, RecruiterJob
from app.auth.models import AnonymousMatchUse
from datetime import date


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def admin_overview(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
):
    return {
        "users_total": session.scalar(select(func.count()).select_from(User)) or 0,
        "published_jobs": session.scalar(
            select(func.count()).select_from(RecruiterJob).where(RecruiterJob.is_published.is_(True))
        ) or 0,
        "applications_total": session.scalar(select(func.count()).select_from(Application)) or 0,
        "anonymous_matches_today": session.scalar(
            select(func.coalesce(func.sum(AnonymousMatchUse.request_count), 0)).where(
                AnonymousMatchUse.usage_date == date.today()
            )
        ) or 0,
        "ai_provider": settings.LLM_PROVIDER,
        "ai_configuration_editable": False,
        "bias_monitoring_available": False,
        "retraining_available": False,
    }


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
) -> list[AdminUserResponse]:
    users = session.scalars(select(User).order_by(User.created_at.desc())).all()
    return [
        AdminUserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )
        for user in users
    ]


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user(
    user_id: str,
    payload: AdminUserUpdate,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_roles("admin")),
) -> AdminUserResponse:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    removes_admin_access = user.role == "admin" and (
        payload.role not in (None, "admin") or payload.is_active is False
    )
    if removes_admin_access:
        active_admins = session.scalar(
            select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
        )
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="Le dernier administrateur actif doit être conservé")
    if user.id == admin.id and (payload.role not in (None, "admin") or payload.is_active is False):
        raise HTTPException(status_code=409, detail="Vous ne pouvez pas retirer vos propres droits admin")

    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if not user.is_active or user.role != "admin":
        user.session_version += 1
    session.commit()
    session.refresh(user)
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )