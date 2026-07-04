"""/user/* endpoints — the contract couvert-app already calls (see FRONT.md §3.2).

Load-bearing semantics:
- GET /user/me returns 404 when no document exists — the app's AuthContext maps
  404 → pendingAccountSetup. Never return an empty 200.
- POST /user/login is called after EVERY Firebase sign-in and must upsert-on-login.
"""

import re

from fastapi import APIRouter, Depends, HTTPException

from api.auth import AuthenticatedUser, get_current_user
from api.deps import get_user_repository
from core.db.user_repository import UserRepository
from core.models.user import UserDoc, UsernameValidation, UserResponse, UserUpdate

router = APIRouter(prefix="/user", tags=["user"])

# Mirrors the app's client-side rule (useUsernameValidation.ts): lowercase, /^[\w]+$/.
USERNAME_RE = re.compile(r"[a-z0-9_]+")
USERNAME_MAX_LENGTH = 30


@router.post("/login", response_model=UserResponse)
async def login(
    payload: UserUpdate | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> UserResponse:
    doc = await repo.get(user.uid)
    if doc is None:
        doc = UserDoc.new(
            user.uid,
            email=user.email,
            email_verified=user.email_verified,
            display_name=user.display_name,
            profile_photo_url=user.photo_url,
        )
    else:
        # Keep identity claims fresh (email verification happens outside our API).
        doc = doc.model_copy(
            update={"email": user.email or doc.email, "email_verified": user.email_verified}
        )
    if payload is not None:
        doc = doc.merged(payload)
    doc = await repo.upsert(doc)
    return doc.to_response()


@router.get("/me", response_model=UserResponse)
async def me(
    user: AuthenticatedUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> UserResponse:
    doc = await repo.get(user.uid)
    if doc is None:
        raise HTTPException(status_code=404, detail="User not found")
    return doc.to_response()


@router.put("/update", response_model=UserResponse)
async def update(
    payload: UserUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> UserResponse:
    doc = await repo.get(user.uid)
    if doc is None:
        doc = UserDoc.new(
            user.uid,
            email=user.email,
            email_verified=user.email_verified,
            display_name=user.display_name,
            profile_photo_url=user.photo_url,
        )
    new_username = (payload.username or "").strip().lower()
    if new_username and new_username != doc.username:
        validation = await _validate(new_username, user.uid, repo)
        if not validation.valid:
            raise HTTPException(status_code=422, detail=validation.message)
        payload = payload.model_copy(update={"username": new_username})
    doc = await repo.upsert(doc.merged(payload))
    return doc.to_response()


@router.delete("/delete")
async def delete(
    user: AuthenticatedUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> dict[str, bool]:
    await repo.delete(user.uid)
    return {"deleted": True}


@router.get("/validate_username", response_model=UsernameValidation)
async def validate_username(
    username: str,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> UsernameValidation:
    return await _validate(username.strip().lower(), user.uid, repo)


@router.get("/profile/{uid}", response_model=UserResponse)
async def profile(
    uid: str,
    user: AuthenticatedUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> UserResponse:
    doc = await repo.get(uid)
    if doc is None:
        raise HTTPException(status_code=404, detail="User not found")
    return doc.to_response()


async def _validate(username: str, own_uid: str, repo: UserRepository) -> UsernameValidation:
    if not username:
        return UsernameValidation(valid=False, message="Informe um nome de usuário.")
    if len(username) > USERNAME_MAX_LENGTH:
        return UsernameValidation(
            valid=False, message=f"Use no máximo {USERNAME_MAX_LENGTH} caracteres."
        )
    if not USERNAME_RE.fullmatch(username):
        return UsernameValidation(
            valid=False, message="Use apenas letras, números e sublinhado."
        )
    if await repo.username_taken(username, exclude_uid=own_uid):
        return UsernameValidation(valid=False, message="Este nome de usuário já está em uso.")
    return UsernameValidation(valid=True, message="Nome de usuário disponível.")
