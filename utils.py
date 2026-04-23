import asyncio
import time
import logging
import filters as fl
import config
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    ChatPermissions,
)

logger = logging.getLogger(__name__)


async def safe_delete(message):
    try:
        await message.delete()
        logger.warning(
            f"Видалено від {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГрупа {message.chat.title} {message.chat.id}\nПовідомлення: {fl.massage_type_check(message)} {message.text}"
        )

        if not message.from_user.is_bot:
            await fl.send_remote_log(
                message,
                config.help_token,
                config.root,
                "DELETE MESSAGE",
            )
    except TelegramBadRequest as e:
        # Message was already deleted by admin or expired — not a real error
        logger.warning(
            f"Message already gone, skipping delete: {e}"
        )
    except Exception as e:
        logger.error(
            f"помилка {e} при видаленні повідомлення від {message.from_user.first_name} {message.from_user.username} {message.from_user.id}"
        )
        await fl.send_remote_log(
            message,
            config.help_token,
            config.root,
            "Помилка при видаленні повідомлення",
        )


async def safe_ban(message, u_id, sec=0):
    try:
        if sec > 0:
            # Бан на час
            end_date = int(time.time()) + sec
            await message.chat.ban(user_id=u_id, until_date=end_date)
        else:
            # Бан назавжди
            await message.chat.ban(user_id=u_id)
        logger.warning(
            f"Заблоковано {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГрупа {message.chat.title} {message.chat.id}"
        )
        await fl.send_remote_log(message, config.help_token, config.root, "BAN USER")
    except Exception as e:
        # Ловимо помилки (наприклад, бот не адмін)
        logger.error(
            f"Помилка {e} блокування користувача {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГрупа {message.chat.title} {message.chat.id}"
        )
        await fl.send_remote_log(
            message,
            config.help_token,
            config.root,
            "Помилка при блокуванні користувача",
        )


async def safe_mute(message, u_id, sec=0):
    try:
        end_date = int(time.time()) + sec

        await message.bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=u_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=end_date,
        )
        logger.warning(
            f"МУТ {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГрупа {message.chat.title} {message.chat.id}"
        )
        await fl.send_remote_log(message, config.help_token, config.root, "MUTE USER")

    except Exception as e:
        logger.error(
            f"Помилка {e} при спроби замутити користувача {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГрупа {message.chat.title} {message.chat.id}"
        )
        await fl.send_remote_log(
            message, config.help_token, config.root, "Помилка під час мут користувача"
        )


async def send_timed_msg(bot, chat_id, text, delay=60):
    try:
        msg_info = await bot.send_message(chat_id=chat_id, text=text)
        await asyncio.sleep(delay)
        await safe_delete(msg_info)
    except Exception as e:
        logging.error(f"не зміг видалити власне повідомлення{e}")
