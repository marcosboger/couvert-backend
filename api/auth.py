"""Firebase ID-token verification.

The app's AxiosHttpClient sends `Authorization: Bearer <firebase-id-token>` on every
request (couvert-app/src/infra/axiosHttpClient.ts).
"""

import threading
from dataclasses import dataclass

import firebase_admin
from fastapi import Depends, HTTPException, Request
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from core.config import Settings, get_settings

_init_lock = threading.Lock()


@dataclass(frozen=True)
class AuthenticatedUser:
    uid: str
    email: str
    email_verified: bool
    display_name: str
    photo_url: str


def _ensure_firebase(settings: Settings) -> None:
    if firebase_admin._apps:
        return
    with _init_lock:
        if firebase_admin._apps:
            return
        if settings.firebase_credentials_path:
            cred = credentials.Certificate(settings.firebase_credentials_path)
            firebase_admin.initialize_app(cred)
        else:
            # Falls back to GOOGLE_APPLICATION_CREDENTIALS / ambient credentials.
            firebase_admin.initialize_app()


def get_current_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> AuthenticatedUser:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Missing bearer token")

    _ensure_firebase(settings)
    try:
        claims = firebase_auth.verify_id_token(token.strip())
    except Exception as exc:  # firebase raises several error types; all mean "not authenticated"
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    return AuthenticatedUser(
        uid=claims["uid"],
        email=claims.get("email", ""),
        email_verified=bool(claims.get("email_verified", False)),
        display_name=claims.get("name", ""),
        photo_url=claims.get("picture", ""),
    )


def get_optional_user(
    request: Request, settings: Settings = Depends(get_settings)
) -> AuthenticatedUser | None:
    """Anonymous-friendly variant: the signup screen validates usernames before any
    Firebase account exists. No Authorization header → None; a present-but-invalid
    token still 401s."""
    if not request.headers.get("Authorization"):
        return None
    return get_current_user(request, settings)
