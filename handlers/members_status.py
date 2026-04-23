import logging
from curses.ascii import isdigit

from aiogram import Router, Bot
from aiogram.types import ChatMemberUpdated
from aiogram.enums import ChatMemberStatus
import filters as fl
import root
from handlers.reports import set_report_status

status_members = Router()
logger = logging.getLogger(__name__)


@status_members.chat_member()
async def track_manual_bans(event: ChatMemberUpdated, bot: Bot, db):
    c_id = event.chat.id
    user_id = event.new_chat_member.user.id
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    admin_statuses = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}

    # Keep ADMINS_CACHE in sync when admins are added or removed
    if c_id in fl.ADMINS_CACHE:
        if new_status in admin_statuses:
            fl.ADMINS_CACHE[c_id].add(user_id)
            await set_report_status(db, user_id, c_id, 1)
        elif old_status in admin_statuses:
            fl.ADMINS_CACHE[c_id].discard(user_id)

    # Always delete from report_mutes on demotion — works even after bot restart
    if old_status in admin_statuses and new_status not in admin_statuses:
        await db.execute(
            "DELETE FROM report_mutes WHERE admin_id = ? AND chat_id = ?",
            (user_id, c_id),
        )
        await db.commit()

    if event.new_chat_member.status == ChatMemberStatus.KICKED:

        if event.from_user.id != bot.id:
            user_banned = event.new_chat_member.user.id
            user_full_name = event.new_chat_member.user.full_name
            admin_who_banned = event.from_user.id
            c_id = event.chat.id
            chat_name = event.chat.title
            lifespan = await fl.get_user_lifespan(db, user_banned, c_id)
            if lifespan is None:
                logger.warning(
                    f"User {user_banned} was banned in {c_id} {chat_name} by admin {admin_who_banned}, lifespan unknown (not in DB)"
                )
                return
            logger.warning(
                f"User {user_banned} was banned in {c_id} {chat_name} by admin {admin_who_banned}, lifespan {lifespan / 60:.1f} min"
            )
            if lifespan / 60 > 400:  # minutes, is old
                return

            await root.user_info(
                bot,
                c_id,
                user_banned,
                user_full_name,
                chat_name,
                f"\n🤲 Ручний бан користувача з ід {user_banned}\nЧас підписки {lifespan / 60} хвилин",
            )
