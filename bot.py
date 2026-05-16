import asyncio
import sys
import time
import aiosqlite
import config
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
)
import filters as fl
from handlers import root
from handlers.admin_panel import admin_router
from handlers.members_status import status_members
from handlers.reaction import message_reaction
from handlers.new_users import new_users
from handlers.reports import report_router
import logging
import messages as msg
import utils
from database import db_manager

# назва файлу створимо власний мікрофон
logger = logging.getLogger(__name__)

logging.basicConfig(
    handlers=[
        logging.FileHandler("my_log.log", encoding="utf-8"),  # Пише у файл
        logging.StreamHandler(),  # Виводить у термінал
    ],
    level=logging.WARNING,
    format="[%(asctime)s] [%(name)s] %(levelname)s (рядок %(lineno)d): %(message)s",
)

TOKEN = config.TOKEN
ADMIN_STATUSES = {"administrator", "creator"}
###################################################################
# Усі обробники мають бути підключені до маршрутизатора (або диспетчера)
dp = Dispatcher()
dp.include_router(admin_router)
# report_router must be before root_router: root_router has a catch-all private handler
# that would eat /reports before report_router ever sees it
dp.include_router(report_router)
dp.include_router(root.root_router)
dp.include_router(status_members)
dp.include_router(message_reaction)
dp.include_router(new_users)

# Wrap echo_handler in its own router so report_router takes priority
main_router = Router()
dp.include_router(main_router)


@main_router.message(F.chat.type.in_({"group", "supergroup"}))
@main_router.edited_message(F.chat.type.in_({"group", "supergroup"}))
async def echo_handler(message: Message, bot: Bot) -> None:
    db: aiosqlite.Connection = await db_manager.get_db()
    if message.from_user and message.from_user.id == 777000:
        return
    if message.new_chat_members or message.left_chat_member:
        return
    ####################
    u_id = message.from_user.id
    fl.ACTIVE_USERS.add(u_id)
    username = message.from_user.username  # username може не бути
    user_full_name = message.from_user.full_name
    c_id = message.chat.id
    # track message so we can bulk-delete on ban
    if u_id not in fl.MSG_HISTORY:
        fl.MSG_HISTORY[u_id] = {}
    if c_id not in fl.MSG_HISTORY[u_id]:
        fl.MSG_HISTORY[u_id][c_id] = {}
    fl.MSG_HISTORY[u_id][c_id][message.message_id] = (time.time(), None)
    chat_name = message.chat.title or "Особисті повідомлення"
    settings = await fl.get_chat_settings(c_id)
    # caption is used when media has a text under it (photo, video, etc.)
    text = message.text or message.caption
    entities = message.entities or message.caption_entities
    # active chats
    if c_id not in root.chats_info:
        root.chats_info[c_id] = chat_name

    if u_id in fl.GLOBAL_BANNED:
        await utils.safe_delete(message)
        await utils.safe_ban(message, u_id)
        asyncio.create_task(
            utils.send_timed_msg(bot, c_id, msg.SpamMessage.spam(user_full_name))
        )
        logger.warning(
            f"Користувач {u_id} заблокований в {c_id} оскільки вже був в BLACK LIST"
        )
        root.stats["global ban"] += 1
        return
    if settings:
        (
            owner_id,
            rus_language,
            stop_word,
            stop_channel,
            stop_links,
            card_number,
            emoji_checker,
            reaction_spam,
        ) = settings

        if message.sender_chat and stop_channel == 1:
            if message.sender_chat.id == message.chat.id:
                return  # це адмін
            elif message.is_automatic_forward:  # репост з каналу який прив'язаний
                return
            # якщо код тут, то це спамер або хтось бажає бути анонімним
            await utils.safe_delete(message)
            root.stats["stop channel"] += 1
            return
        ## Перевірок на шлюхо-символи
        if text and fl.has_weird_chars(text):
            await utils.safe_delete(message)  # Безпечне видалення
            await utils.safe_ban(message, u_id)
            asyncio.create_task(
                utils.send_timed_msg(bot, c_id, msg.SpamMessage.spam(user_full_name))
            )
            root.stats["bad chars"] += 1
            return
        if text and card_number == 1 and fl.check_card(text):
            try:  # Якщо було спрацювання
                member_chat = await bot.get_chat_member(
                    chat_id=c_id, user_id=message.from_user.id
                )
                if member_chat.status in ADMIN_STATUSES:
                    pass  # все ок адмінам можна
                else:
                    await utils.safe_delete(message)
                    asyncio.create_task(
                        utils.send_timed_msg(
                            bot,
                            c_id,
                            msg.SpamMessage.stop_card_number(u_id, user_full_name),
                        )
                    )
                    root.stats["card numbers"] += 1
                    return  # Чат чистий, далі не йдемо
            except Exception as e:
                logger.error(f"щось не так апм спрацюванні номеру карти {e}")
                await utils.safe_delete(message)
                asyncio.create_task(
                    utils.send_timed_msg(
                        bot,
                        c_id,
                        msg.SpamMessage.stop_card_number(u_id, user_full_name),
                    )
                )
                return  # Чат чистий, далі не йдемо
        if text and emoji_checker == 1:
            kef = fl.emoji_checker(text)
            if kef >= 90:
                pass
            elif kef >= 70:
                await utils.safe_delete(message)
                # await bot.delete_message(chat_id=-1001234567890, message_id=2493340)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"emoji checker\n\n{(text or 'Медіа')[:200]}",
                )
                asyncio.create_task(
                    utils.send_timed_msg(
                        bot, c_id, msg.SpamMessage.emoji_spam(user_full_name)
                    )
                )
                root.stats["emoji checker"] += 1
                return
            else:
                await utils.safe_delete(message)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"emoji checker\n\n{(text or 'Медіа')[:200]}",
                )
                # Мут
                await utils.safe_mute(message, u_id)
                asyncio.create_task(
                    utils.send_timed_msg(
                        bot, c_id, msg.SpamMessage.emoji_spam(user_full_name)
                    )
                )
                root.stats["emoji checker"] += 1
                return
        if stop_links == 1:
            bad_types = {"mention", "url", "text_link"}
            if entities and any(e.type in bad_types for e in entities):
                try:  # Якщо було спрацювання
                    member_chat = await bot.get_chat_member(
                        chat_id=c_id, user_id=message.from_user.id
                    )
                    if member_chat.status in ADMIN_STATUSES:
                        pass  # все ок адмінам можна
                    elif fl.is_good_mention(entities, text):
                        pass
                    else:
                        await utils.safe_delete(message)
                        root.stats["stop links"] += 1
                        if fl.count_links(u_id, c_id):
                            await utils.safe_mute(message, u_id)
                            asyncio.create_task(
                                utils.send_timed_msg(
                                    bot,
                                    c_id,
                                    msg.SpamMessage.stop_links_mute(
                                        u_id, user_full_name
                                    ),
                                )
                            )
                        else:
                            asyncio.create_task(
                                utils.send_timed_msg(
                                    bot,
                                    c_id,
                                    msg.SpamMessage.stop_links(u_id, user_full_name),
                                )
                            )
                            return
                except Exception as e:
                    logger.error(f"щось не так при спрацюванні посилання {e}")
                    await utils.safe_delete(message)
                    asyncio.create_task(
                        utils.send_timed_msg(
                            bot, c_id, msg.SpamMessage.stop_links(u_id, user_full_name)
                        )
                    )
                    return

        ###################
        # Запис або оновлення паспорта
        await fl.register_or_update_passport(u_id, user_full_name, username)
        # перевірка чи є в базі як підписник каналу ?
        if not await fl.msg_count(u_id, c_id):
            await db.execute(
                """
                INSERT INTO chat_stats (user_id, channel_id, msg_count, join_date)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP) ON CONFLICT(user_id, channel_id) 
                        DO
                UPDATE SET msg_count = msg_count + 1
                """,
                (u_id, c_id),
            )
            await db.commit()
            fl.msg_count.cache_invalidate(u_id, c_id)
            dc_number = await fl.check_dc_number(bot, u_id)
            if dc_number == 100:
                await utils.safe_delete(message)
                await utils.safe_ban(message, u_id)
                root.stats["found hash"] += 1
                fl.GLOBAL_BANNED.add(int(u_id))
                await utils.delete_user_history(bot, u_id)
                # status 1 is ban
                await fl.change_user_status(int(u_id), 1)
                asyncio.create_task(
                    utils.send_timed_msg(
                        bot, c_id, msg.SpamMessage.spam_18(user_full_name)
                    )
                )
                return
            elif dc_number in [1, 5] and not message.from_user.is_bot:
                await utils.safe_delete(message)
                await utils.safe_mute(message, u_id)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"DC {dc_number}\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{fl.generate_message_link(message)}\n\n{(text or 'Медіа')[:200]}",
                )
                asyncio.create_task(
                    utils.send_timed_msg(
                        bot, c_id, msg.SpamMessage.mute(user_full_name)
                    )
                )
                root.stats["bad dc"] += 1
                return
            bio = await fl.check_user_bio(bot, u_id)
            if bio:
                if bio == 100:
                    await utils.safe_delete(message)
                    await utils.safe_ban(message, u_id)
                    asyncio.create_task(
                        utils.send_timed_msg(
                            bot, c_id, msg.SpamMessage.spam(user_full_name)
                        )
                    )
                    fl.GLOBAL_BANNED.add(int(u_id))
                    await utils.delete_user_history(bot, u_id)
                    root.stats["bad bio"] += 1
                    return
                else:  # тимчасово щоб наповнити базу
                    chat_info = await bot.get_chat(u_id)
                    bio = chat_info.bio
                    await root.user_info(
                        bot,
                        c_id,
                        u_id,
                        user_full_name,
                        chat_name,
                        f"Біо\n\n{bio}\n\n{fl.generate_message_link(message)}\n\n{(text or '')[:200]}",
                        message.message_id,
                    )
            if await fl.check_user_avatar(bot, message.from_user.id):
                # тепер тут тільки оповіщення для ручної перевірки
                # варто зробити подвійну перевірку з інтервалом для тих в кого фото нема
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"Фото\nn⛔️⛔️⛔️⛔️⛔️⛔️\n{fl.generate_message_link(message)}\n\n{(text or '')[:200]}",
                )
            if message.from_user.is_premium and u_id > 7700000000:
                ################################################################################
                if text:
                    if await fl.is_spam(text):
                        # винести функцією показала гуд
                        await utils.safe_ban(message, u_id)
                        await utils.safe_delete(message)
                        asyncio.create_task(
                            utils.send_timed_msg(
                                bot, c_id, msg.SpamMessage.spam(user_full_name)
                            )
                        )
                        await root.user_info(
                            bot,
                            c_id,
                            u_id,
                            user_full_name,
                            chat_name,
                            f"ПРЕМІУМ AI\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{fl.generate_message_link(message)}\n\n{(text or 'Медіа')[:200]}",
                        )
                        fl.GLOBAL_BANNED.add(int(u_id))
                        await utils.delete_user_history(bot, u_id)
                        # status 1 is ban
                        await fl.change_user_status(int(u_id), 1)
                        root.stats["premium work"] += 1
                        return
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"ПРЕМІУМ\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{fl.generate_message_link(message)}\n\n{(text or 'Медіа')[:200]}",
                    message.message_id,
                )

        else:
            if text and rus_language == 1:
                if fl.rus_language(text):
                    await utils.safe_delete(message)
                    asyncio.create_task(
                        utils.send_timed_msg(
                            bot, c_id, msg.SpamMessage.russian_language(user_full_name)
                        )
                    )

            # тут будуть функції які адмін може вмикати вимикати
            # stop words
    else:  # Схоже нас щойно додали в цей чат треба запис в базу створити
        c_id = message.chat.id
        try:
            real_owner_id = await fl.get_channel_owner(bot, c_id)
            await db.execute(
                "INSERT OR IGNORE INTO chat_links (chat_id, owner_id) VALUES (?, ?)",
                (c_id, real_owner_id),
            )
            await db.commit()
            # cache
            fl.get_chat_settings.cache_invalidate(c_id)
            logger.warning(f":Додано новий чат\n{message.chat.title} ({c_id})")
        except Exception as e:
            logger.error(
                f"Помилка при отриманні ід власника {e}\nймовірно в бота поки що недостатньо прав\n{e}"
            )

            return


####
async def _flush_loop():
    """Background task: flush active users to DB every 10 minutes."""
    while True:
        await asyncio.sleep(600)
        await fl.flush_active_users()


async def main() -> None:
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await db_manager.connect()
        await fl.load_hashes()
        await fl.load_banned_users()
        await fl.load_passport_cache()
        asyncio.create_task(_flush_loop())
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "edited_message",
                "chat_member",
                "callback_query",
                "message_reaction",
            ],
        )
    finally:
        await db_manager.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
