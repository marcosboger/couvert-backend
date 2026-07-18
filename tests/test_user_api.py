"""Contract tests for /user/* — semantics couvert-app depends on (FRONT.md §3.2)."""

from tests.conftest import TEST_USER, InMemoryUserRepository

FULL_UPDATE = {
    "username": "giovannaprezia",
    "display_name": "giovannaprezia",
    "email": "giovanna@example.com",
    "profile_photo_url": "https://example.com/photo.jpg",
    "age": "28",
    "phone": "+5511999999999",
    "name": "Giovanna Prezia",
    "address": "Rua X, 123",
    "city": "São Paulo",
    "state": "SP",
    "zip_code": "01310-000",
    "email_verified": True,
}


async def test_me_without_token_is_401(unauthenticated_client):
    async with unauthenticated_client as client:
        response = await client.get("/user/me")
    assert response.status_code == 401


async def test_me_without_doc_is_404(client):
    """AuthContext maps this 404 to pendingAccountSetup — must never be an empty 200."""
    async with client:
        response = await client.get("/user/me")
    assert response.status_code == 404


async def test_login_creates_skeleton_from_claims(client, repo: InMemoryUserRepository):
    async with client:
        response = await client.post("/user/login")
    assert response.status_code == 200
    body = response.json()
    assert body["uid"] == TEST_USER.uid
    assert body["email"] == TEST_USER.email
    assert body["email_verified"] is True
    assert body["username"] == ""  # no username yet → app routes to account setup
    assert body["created_at"]
    assert TEST_USER.uid in repo.docs


async def test_login_twice_returns_same_doc(client):
    async with client:
        first = (await client.post("/user/login")).json()
        second = (await client.post("/user/login")).json()
    assert first["created_at"] == second["created_at"]
    assert first["uid"] == second["uid"]


async def test_login_merges_signup_payload(client):
    async with client:
        response = await client.post("/user/login", json={"name": "Giovanna Prezia"})
    assert response.json()["name"] == "Giovanna Prezia"


async def test_update_round_trips_all_wire_fields(client):
    async with client:
        await client.post("/user/login")
        response = await client.put("/user/update", json=FULL_UPDATE)
        body = response.json()
        me = (await client.get("/user/me")).json()
    assert response.status_code == 200
    for field, value in FULL_UPDATE.items():
        assert body[field] == value, field
        assert me[field] == value, field
    # string-typed scalars must stay strings (app wire format)
    assert isinstance(me["age"], str)
    assert isinstance(me["zip_code"], str)


async def test_update_rejects_taken_username(client, repo: InMemoryUserRepository):
    from core.models.user import UserDoc

    other = UserDoc.new("uid-2")
    repo.docs["uid-2"] = other.model_copy(update={"username": "taken"})
    async with client:
        await client.post("/user/login")
        response = await client.put("/user/update", json={"username": "taken"})
    assert response.status_code == 422


async def test_validate_username_free_taken_own_and_invalid(
    client, repo: InMemoryUserRepository
):
    from core.models.user import UserDoc

    other = UserDoc.new("uid-2")
    repo.docs["uid-2"] = other.model_copy(update={"username": "taken"})
    async with client:
        await client.post("/user/login")
        await client.put("/user/update", json={"username": "giovannaprezia"})

        free = (await client.get("/user/validate_username?username=livre")).json()
        taken = (await client.get("/user/validate_username?username=taken")).json()
        own = (await client.get("/user/validate_username?username=giovannaprezia")).json()
        invalid = (await client.get("/user/validate_username?username=não válido")).json()

    assert free["valid"] is True
    assert taken["valid"] is False
    assert own["valid"] is True  # revalidating your own username must pass
    assert invalid["valid"] is False
    for result in (free, taken, own, invalid):
        assert isinstance(result["message"], str) and result["message"]


async def test_validate_username_works_without_token(
    unauthenticated_client, repo: InMemoryUserRepository
):
    """The signup screen checks availability before any Firebase account exists."""
    from core.models.user import UserDoc

    other = UserDoc.new("uid-2")
    repo.docs["uid-2"] = other.model_copy(update={"username": "taken"})
    async with unauthenticated_client as client:
        free = (await client.get("/user/validate_username?username=livre")).json()
        taken = (await client.get("/user/validate_username?username=taken")).json()

    assert free["valid"] is True
    assert taken["valid"] is False


async def test_delete_then_me_is_404(client):
    async with client:
        await client.post("/user/login")
        deleted = await client.delete("/user/delete")
        again = await client.delete("/user/delete")  # idempotent
        me = await client.get("/user/me")
    assert deleted.status_code == 200
    assert again.status_code == 200
    assert me.status_code == 404


async def test_profile_of_other_user(client, repo: InMemoryUserRepository):
    from core.models.user import UserDoc

    other = UserDoc.new("uid-2")
    repo.docs["uid-2"] = other.model_copy(update={"username": "amiga"})
    async with client:
        found = await client.get("/user/profile/uid-2")
        missing = await client.get("/user/profile/uid-nope")
    assert found.status_code == 200
    assert found.json()["username"] == "amiga"
    assert missing.status_code == 404
