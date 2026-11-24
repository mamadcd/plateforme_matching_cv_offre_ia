from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic
from typing import Callable

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.database import get_db_session
from app.auth.models import User
from app.auth.schemas import LoginRequest, RegisterRequest, UserResponse
from app.core.config import settings


router = APIRouter(prefix="/auth", tags=["auth"])
password_hash = PasswordHash.recommended()
COOKIE_NAME = "matching_session"
JWT_ALGORITHM = "HS256"
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60
login_attempts: dict[tuple[str, str], list[float]] = {}
login_attempts_lock = Lock()


def _login_attempt_key(email: str, request: Request) -> tuple[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    return email, client_ip


def _check_login_attempt_limit(key: tuple[str, str]) -> None:
    now = monotonic()
    cutoff = now - LOGIN_WINDOW_SECONDS
    with login_attempts_lock:
        attempts = [attempt_at for attempt_at in login_attempts.get(key, []) if attempt_at >= cutoff]
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=429,
                detail="Trop de tentatives de connexion. Réessayez dans quelques minutes.",
            )


def _record_failed_login(key: tuple[str, str]) -> None:
    now = monotonic()
    cutoff = now - LOGIN_WINDOW_SECONDS
    with login_attempts_lock:
        attempts = [attempt_at for attempt_at in login_attempts.get(key, []) if attempt_at >= cutoff]
        attempts.append(now)
        login_attempts[key] = attempts


def _clear_failed_logins(key: tuple[str, str]) -> None:
    with login_attempts_lock:
        login_attempts.pop(key, None)


def _configured_secret() -> str:
    if len(settings.AUTH_SECRET_KEY) < 32:
        raise HTTPException(
            status_code=503,
            detail="AUTH_SECRET_KEY doit contenir au moins 32 caractères",
        )
    return settings.AUTH_SECRET_KEY


def _set_session_cookie(response: Response, user: User) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.AUTH_TOKEN_EXPIRE_MINUTES)
    token = jwt.encode(
        {"sub": user.id, "role": user.role, "ver": user.session_version, "exp": expires_at},
        _configured_secret(),
        algorithm=JWT_ALGORITHM,
    )
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email, full_name=user.full_name, role=user.role)


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    session: Session = Depends(get_db_session),
) -> UserResponse:
    _configured_secret()
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=password_hash.hash(payload.password),
        role=payload.role,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="Cette adresse e-mail est déjà utilisée") from error

    session.refresh(user)
    _set_session_cookie(response, user)
    return _user_response(user)


@router.post("/login", response_model=UserResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: Session = Depends(get_db_session),
) -> UserResponse:
    _configured_secret()
    email = payload.email.strip().casefold()
    attempt_key = _login_attempt_key(email, request)
    _check_login_attempt_limit(attempt_key)
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not password_hash.verify(payload.password, user.password_hash):
        _record_failed_login(attempt_key)
        raise HTTPException(status_code=401, detail="Adresse e-mail ou mot de passe incorrect")
    if not user.is_active:
        _record_failed_login(attempt_key)
        raise HTTPException(status_code=403, detail="Ce compte est désactivé")

    _clear_failed_logins(attempt_key)
    _set_session_cookie(response, user)
    return _user_response(user)


def get_current_user(
    session: Session = Depends(get_db_session),
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Connexion requise")

    try:
        claims = jwt.decode(token, _configured_secret(), algorithms=[JWT_ALGORITHM])
        user_id = claims["sub"]
        session_version = claims["ver"]
    except (jwt.InvalidTokenError, KeyError, TypeError) as error:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée") from error

    user = session.get(User, user_id)
    if user is None or not user.is_active or user.session_version != session_version:
        raise HTTPException(status_code=401, detail="Session invalide ou expirée")
    return user


@router.get("/me", response_model=UserResponse)
def current_user(user: User = Depends(get_current_user)) -> UserResponse:
    return _user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> Response:
    user.session_version += 1
    session.commit()
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def require_roles(*roles: str) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Accès refusé pour ce rôle")
        return user

    return dependency