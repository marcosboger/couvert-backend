from fastapi import HTTPException, Request

from core.db.user_repository import UserRepository


def get_user_repository(request: Request) -> UserRepository:
    repo: UserRepository | None = getattr(request.app.state, "user_repository", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    return repo
