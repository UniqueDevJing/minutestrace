from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User
from .models import AgentRun, Meeting


bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def issue_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user.id), "role": user.role, "iat": now, "exp": now + timedelta(minutes=settings.jwt_ttl_minutes)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    try:
        payload = jwt.decode(credentials.credentials, get_settings().jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效") from exc
    user = db.get(User, user_id)
    if not user or not user.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def authorize_meeting(db: Session, meeting_id: int, user: User) -> Meeting:
    """Enforce object-level meeting access before any related resource is read or changed."""
    meeting = db.get(Meeting, meeting_id)
    if not meeting or (user.role != "admin" and meeting.owner_id != user.id):
        # Return 404 for foreign resources so IDs cannot be enumerated.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会议不存在")
    return meeting


def authorize_run(db: Session, run_id: int, user: User) -> AgentRun:
    """Apply the same ownership boundary to review runs and their event stream."""
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="审校运行不存在")
    authorize_meeting(db, run.meeting_id, user)
    return run
