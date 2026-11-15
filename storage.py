from motor.motor_asyncio import AsyncIOMotorClient
from config import config


class Storage:
    def __init__(self):
        self.client = AsyncIOMotorClient(config.mongo_uri)
        self.db = self.client[config.db_name]
        self.users = self.db["hosted_users"]

    async def initialize(self):
        await self.users.create_index("user_id", unique=True)
        await self.users.create_index("private_group_id", sparse=True)

    async def get_user(self, user_id: int):
        return await self.users.find_one({"user_id": int(user_id)})

    async def get_by_private_group(self, chat_id: int):
        return await self.users.find_one({"private_group_id": int(chat_id)})

    async def save_user(self, user_id: int, **fields):
        await self.users.update_one(
            {"user_id": int(user_id)},
            {"$set": {"user_id": int(user_id), **fields}},
            upsert=True,
        )

    async def delete_user(self, user_id: int):
        # All settings, private-group mapping, active-pair state and the
        # encrypted session live in this one user-owned document.
        await self.users.delete_one({"user_id": int(user_id)})

    async def all_users(self):
        return await self.users.find({}).to_list(length=None)

    async def close(self):
        self.client.close()
