"""User wire models.

Field names and types mirror the app exactly (snake_case, scalar strings):
couvert-app/src/wire/in/UserWire.ts (responses) and out/UserWire.ts (update requests).
`age`, `phone` and `zip_code` are strings in the app's wire format — keep them strings.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

FriendshipStatus = Literal["accepted", "pending"]


class UserResponse(BaseModel):
    """Wire shape the app parses in wireToInternalUser (UserAdapter.ts)."""

    uid: str
    username: str = ""
    display_name: str = ""
    email: str = ""
    profile_photo_url: str = ""
    age: str = ""
    phone: str = ""
    name: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    email_verified: bool = False

    has_friendship: bool | None = None
    friendship_status: FriendshipStatus | None = None
    friendship_id: str | None = None
    created_at: str | None = None


class UserUpdate(BaseModel):
    """Wire shape the app sends (internalUserToWire → UserUpdateWire).

    The TS type declares every field, but be lenient: partial payloads are accepted
    and merged over the stored document.
    """

    model_config = ConfigDict(extra="ignore")

    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    profile_photo_url: str | None = None
    age: str | None = None
    phone: str | None = None
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    email_verified: bool | None = None


class UserDoc(UserResponse):
    """Cosmos document: wire shape + `id` (= uid, enables point reads)."""

    id: str

    @classmethod
    def new(
        cls,
        uid: str,
        *,
        email: str = "",
        email_verified: bool = False,
        display_name: str = "",
        profile_photo_url: str = "",
    ) -> "UserDoc":
        return cls(
            id=uid,
            uid=uid,
            email=email,
            email_verified=email_verified,
            display_name=display_name,
            profile_photo_url=profile_photo_url,
            created_at=datetime.now(UTC).isoformat(),
        )

    def merged(self, update: UserUpdate) -> "UserDoc":
        changes = update.model_dump(exclude_none=True)
        return self.model_copy(update=changes)

    def to_response(self) -> UserResponse:
        return UserResponse.model_validate(self.model_dump(exclude={"id"}))


class UsernameValidation(BaseModel):
    valid: bool
    message: str
