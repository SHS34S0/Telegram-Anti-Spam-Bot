import logging

import aiosqlite
from aiogram import Router, Bot
from aiogram.filters import ChatMemberUpdatedFilter, MEMBER, IS_NOT_MEMBER
from aiogram.types import ChatMemberUpdated
import filters as fl

new_users = Router()
logger = logging.getLogger(__name__)


# обробка вступу
@new_users.chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> MEMBER)
)
async def on_user_join(event: ChatMemberUpdated, db: aiosqlite.Connection):
    c_id = event.chat.id
    user_id = event.new_chat_member.user.id
    full_name = event.new_chat_member.user.full_name
    username = event.new_chat_member.user.username  # Може бути None

    await fl.register_or_update_passport(db, user_id, full_name, username)
    await db.execute(
        """
        INSERT INTO chat_stats (user_id, channel_id, join_date)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, channel_id) DO UPDATE SET join_date = CURRENT_TIMESTAMP
        """,
        (user_id, c_id),
    )
    await db.commit()
    logger.warning(
        f"Користувач {full_name} ({username}, {user_id}) приєднався до чату {event.chat.title} ({c_id})"
    )
