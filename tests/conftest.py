import httpx
import pytest

from api.auth import AuthenticatedUser, get_current_user, get_optional_user
from api.deps import get_user_repository
from api.main import app
from core.models.user import UserDoc


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.docs: dict[str, UserDoc] = {}

    async def get(self, uid: str) -> UserDoc | None:
        return self.docs.get(uid)

    async def upsert(self, user: UserDoc) -> UserDoc:
        self.docs[user.uid] = user
        return user

    async def delete(self, uid: str) -> None:
        self.docs.pop(uid, None)

    async def username_taken(self, username: str, exclude_uid: str | None = None) -> bool:
        return any(
            doc.username == username and doc.uid != exclude_uid for doc in self.docs.values()
        )


TEST_USER = AuthenticatedUser(
    uid="uid-1",
    email="giovanna@example.com",
    email_verified=True,
    display_name="Giovanna",
    photo_url="https://example.com/photo.jpg",
)


@pytest.fixture
def repo() -> InMemoryUserRepository:
    return InMemoryUserRepository()


@pytest.fixture
def client(repo: InMemoryUserRepository):
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    app.dependency_overrides[get_optional_user] = lambda: TEST_USER
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(repo: InMemoryUserRepository):
    """Real auth dependency (no Firebase creds) — requests without tokens must 401."""
    app.dependency_overrides[get_user_repository] = lambda: repo
    transport = httpx.ASGITransport(app=app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()
