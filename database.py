import aiosqlite
import os
import logging

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self.db: aiosqlite.Connection | None = None

    async def connect(self, db_path="db/anti_spam.db"):
        if self.db is None:
            file_exists = os.path.exists(db_path)
            self.db = await aiosqlite.connect(db_path)

            # create tables from schema if db file is new
            if not file_exists:
                try:
                    with open("db/schema.sql") as s:
                        schema = s.read()
                        await self.db.executescript(schema)
                        await self.db.commit()
                except FileNotFoundError:
                    logger.error("db/schema.sql not found")

        return self.db

    async def get_db(self) -> aiosqlite.Connection:
        if self.db is None:
            raise RuntimeError("Call connect() first in main()")
        return self.db

    async def close(self):
        if self.db:
            await self.db.close()
            self.db = None


db_manager = DatabaseManager()