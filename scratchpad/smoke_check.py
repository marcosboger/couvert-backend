"""Quick live check: Cosmos connectivity + Firebase Admin credential init."""

import asyncio

import firebase_admin
from azure.cosmos.aio import CosmosClient
from firebase_admin import credentials

from core.config import get_settings

s = get_settings()
print("cosmos db name:", s.cosmos_database)

cred = credentials.Certificate(s.firebase_credentials_path)
app = firebase_admin.initialize_app(cred)
print("firebase project:", app.project_id)


async def main() -> None:
    async with CosmosClient(s.cosmos_endpoint, s.cosmos_key) as client:
        db = client.get_database_client(s.cosmos_database)
        names = [c["id"] async for c in db.list_containers()]
        print("containers:", names)
        rc = db.get_container_client("restaurants")
        count = [x async for x in rc.query_items("SELECT VALUE COUNT(1) FROM c")]
        print("restaurants seeded:", count[0])
        uc = db.get_container_client("users")
        ucount = [x async for x in uc.query_items("SELECT VALUE COUNT(1) FROM c")]
        print("user docs:", ucount[0])


asyncio.run(main())
