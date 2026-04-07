import logging
from curses.ascii import isdigit

from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.enums import ChatMemberStatus
import filters as fl
import root

status_members = Router()
logger = logging.getLogger(__name__)


@status_members.chat_member()
async def track_manual_bans(event: ChatMemberUpdated, bot: Bot, db):
    if event.new_chat_member.status == ChatMemberStatus.KICKED:

        if event.from_user.id != bot.id:
            user_banned = event.new_chat_member.user.id
            user_full_name = event.new_chat_member.user.full_name
            admin_who_banned = event.from_user.id
            c_id = event.chat.id
            chat_name = event.chat.title
            lifespan = await fl.get_user_lifespan(db, user_banned, c_id)
            if lifespan is None:
                return
            if lifespan / 60 > 400:  # minutes, is old
                return
            logger.warning(
                f"Користувач {user_banned} був заблокований в {c_id} {chat_name} адміністратором {admin_who_banned} час життя в чаті {lifespan / 60} хвилин"
            )

            await root.user_info(
                bot,
                c_id,
                user_banned,
                user_full_name,
                chat_name,
                f"\n🤲 Ручний бан користувача з ід {user_banned}\nЧас підписки {lifespan / 60} хвилин",
            )
