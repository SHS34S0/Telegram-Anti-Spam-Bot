import asyncio
import sys
import time
import aiosqlite
import config
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER
from aiogram.types import (
    Message,
    ChatMemberUpdated,
    CallbackQuery,
    InlineKeyboardButton,
    ChatPermissions,
)

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import MessageReactionUpdated

import filters as fl
import root
from admin_panel import admin_router
import logging
import messages as msg

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
VOITS = 3
BAN24 = 86400
ADMIN_STATUSES = {"administrator", "creator"}

# варто переконатись чи то ще треба
GOOD_STATUSES = {"member", "administrator", "creator"}


###############################
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
        pass


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


###################################################################
# Усі обробники мають бути підключені до маршрутизатора (або диспетчера)

dp = Dispatcher()
dp.include_router(admin_router)
dp.include_router(root.root_router)


##########################################################################################


@dp.message_reaction()
async def reaction_handler(
        reaction: MessageReactionUpdated, bot: Bot, db: aiosqlite.Connection
):
    user = reaction.user
    if not user:
        return  # це може бути анонімний адмін або канал

    u_id = user.id
    c_id = reaction.chat.id
    user_full_name = reaction.user.full_name
    #  МИЛИЦЯ видалення повідомлення через 🤡
    if str(u_id) == str(config.root):
        for react in reaction.new_reaction:
            if getattr(react, "emoji", None) == "🤡":
                try:
                    await bot.delete_message(
                        chat_id=c_id, message_id=reaction.message_id
                    )
                except Exception as e:
                    logger.error(
                        f"Помилка {e} при спробі видалити повідомлення через реакцію 🤡 від користувача {user_full_name} ({u_id})\nГрупа {reaction.chat.title} ({c_id})"
                    )
                return
    # ==========================================================
    if await fl.msg_count(db, u_id, c_id):
        return
    # Ставить реакції. чи забирає ?
    if not reaction.new_reaction:
        return
    dc_number = await fl.check_dc_number(bot, u_id)
    if dc_number == 100:
        await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
        logger.warning(
            f"Заблоковано {user_full_name} {u_id}\nГрупа {reaction.chat.title} {c_id} \nПричина: Reaction Spam"
        )

        asyncio.create_task(
            send_timed_msg(bot, c_id, msg.SpamMessage.reaction_spam(user_full_name))
        )
        return


# обробка вступу
@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> MEMBER))
async def on_user_join(event: ChatMemberUpdated, db: aiosqlite.Connection):
    c_id = event.chat.id
    user_id = event.new_chat_member.user.id
    full_name = event.new_chat_member.user.full_name
    username = event.new_chat_member.user.username  # Може бути None

    await fl.register_or_update_passport(db, user_id, full_name, username)
    await db.execute(
        """
        INSERT INTO chat_stats (user_id, channel_id, join_date)
        VALUES (?, ?, CURRENT_TIMESTAMP) ON CONFLICT(user_id, channel_id) DO
        UPDATE SET join_date = CURRENT_TIMESTAMP
        """,
        (user_id, c_id),
    )
    await db.commit()
    logger.warning(
        f"Користувач {full_name} ({username}, {user_id}) приєднався до чату {event.chat.title} ({c_id})"
    )


############
@dp.message(F.chat.type.in_({"group", "supergroup"}))
@dp.edited_message(F.chat.type.in_({"group", "supergroup"}))
async def echo_handler(message: Message, bot: Bot, db: aiosqlite.Connection) -> None:
    if message.from_user and message.from_user.id == 777000:
        print("finish")
        return
    if message.new_chat_members or message.left_chat_member:
        return
    ####################
    u_id = message.from_user.id
    username = message.from_user.username  # username може не бути
    user_full_name = message.from_user.full_name
    c_id = message.chat.id
    chat_name = message.chat.title or "Особисті повідомлення"
    settings = await fl.get_chat_settings(db, c_id)

    if settings:
        (
            owner_id,
            voting_buttons,
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
            await safe_delete(message)
            return
        ## Перевірок на шлюхо-символи
        if message.text and fl.has_weird_chars(message.text):
            await safe_delete(message)  # Безпечне видалення
            await safe_ban(message, u_id)
            await root.user_info(
                bot,
                c_id,
                u_id,
                user_full_name,
                chat_name,
                f"Шлюхо-символ\n\n{message.text[:800]}",
            )
            asyncio.create_task(
                send_timed_msg(bot, c_id, msg.SpamMessage.spam(user_full_name))
            )
            return
        if message.text and card_number == 1 and fl.check_card(message.text):
            try:  # Якщо було спрацювання
                member_chat = await bot.get_chat_member(
                    chat_id=c_id, user_id=message.from_user.id
                )
                if member_chat.status in ADMIN_STATUSES:
                    pass  # все ок адмінам можна
                else:
                    await safe_delete(message)
                    asyncio.create_task(
                        send_timed_msg(
                            bot,
                            c_id,
                            msg.SpamMessage.stop_card_number(u_id, user_full_name),
                        )
                    )
                    return  # Чат чистий, далі не йдемо
            except Exception as e:
                logger.error(f"щось не так апм спрацюванні номеру карти {e}")
                await safe_delete(message)
                asyncio.create_task(
                    send_timed_msg(
                        bot,
                        c_id,
                        msg.SpamMessage.stop_card_number(u_id, user_full_name),
                    )
                )
                return  # Чат чистий, далі не йдемо
        if message.text and emoji_checker == 1:
            kef = fl.emoji_checker(message.text)
            if kef >= 90:
                pass
            elif kef >= 70:
                await safe_delete(message)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"emoji checker\n\n{message.text[:800]}",
                )
                asyncio.create_task(
                    send_timed_msg(
                        bot, c_id, msg.SpamMessage.emoji_spam(user_full_name)
                    )
                )
                return
            else:
                await safe_delete(message)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"emoji checker\n\n{message.text[:800]}",
                )
                # Мут
                await safe_mute(message, u_id)
                asyncio.create_task(
                    send_timed_msg(
                        bot, c_id, msg.SpamMessage.emoji_spam(user_full_name)
                    )
                )
                return
        if stop_links == 1:
            bad_types = {"mention", "url", "text_link"}
            if message.entities and any(e.type in bad_types for e in message.entities):
                try:  # Якщо було спрацювання
                    member_chat = await bot.get_chat_member(
                        chat_id=c_id, user_id=message.from_user.id
                    )
                    if member_chat.status in ADMIN_STATUSES:
                        print("Адміністратор")
                        pass  # все ок адмінам можна
                    elif fl.is_good_mention(message.entities, message.text):
                        pass
                    else:
                        await safe_delete(message)
                        asyncio.create_task(
                            send_timed_msg(
                                bot,
                                c_id,
                                msg.SpamMessage.stop_links(u_id, user_full_name),
                            )
                        )
                        return  # Чат чистий, далі не йдемо
                except Exception as e:
                    logger.error(f"щось не так при спрацюванні посилання {e}")
                    await safe_delete(message)
                    asyncio.create_task(
                        send_timed_msg(
                            bot, c_id, msg.SpamMessage.stop_links(u_id, user_full_name)
                        )
                    )
                    return  # Чат чистий, далі не йдемо

        ###################
        # Запис або оновлення паспорта
        await fl.register_or_update_passport(db, u_id, user_full_name, username)
        # перевірка чи є в базі як підписник каналу ?
        if not await fl.msg_count(db, u_id, c_id):
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
            fl.msg_count.cache_invalidate(db, u_id, c_id)
            dc_number = await fl.check_dc_number(bot, u_id)
            if dc_number == 100:
                await safe_delete(message)
                await safe_ban(message, u_id)
                asyncio.create_task(
                    send_timed_msg(bot, c_id, msg.SpamMessage.spam_18(user_full_name))
                )
                return
            elif dc_number in [1, 5] and not message.from_user.is_bot:
                await safe_delete(message)
                await safe_mute(message, u_id)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"DC {dc_number}\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{fl.generate_message_link(message)}\n\n{message.text[:800]}",
                )
                asyncio.create_task(
                    send_timed_msg(bot, c_id, msg.SpamMessage.spam(user_full_name))
                )
                return
            bio = await fl.check_user_bio(bot, u_id)
            if bio:
                if bio == 100:
                    await safe_delete(message)
                    await safe_ban(message, u_id)
                    asyncio.create_task(
                        send_timed_msg(bot, c_id, msg.SpamMessage.spam(user_full_name))
                    )
                    await root.user_info(
                        bot,
                        c_id,
                        u_id,
                        user_full_name,
                        chat_name,
                        f"Біо БАН\n{fl.generate_message_link(message)}\n\n{message.text[:800]}",
                    )
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
                        f"Біо\n{bio}\n{fl.generate_message_link(message)}\n\n{message.text[:800]}",
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
                    f"Фото\nn⛔️⛔️⛔️⛔️⛔️⛔️\n{fl.generate_message_link(message)}\n\n{message.text[:800]}",
                )
            if message.from_user.is_premium and u_id > 7700000000:
                ################################################################################
                if message.text:
                    if await fl.is_spam(message.text):
                        # винести функцією показала гуд
                        await safe_ban(message, u_id)
                        await safe_delete(message)
                        asyncio.create_task(
                            send_timed_msg(
                                bot, c_id, msg.SpamMessage.spam(user_full_name)
                            )
                        )
                        await root.user_info(
                            bot,
                            c_id,
                            u_id,
                            user_full_name,
                            chat_name,
                            f"ПРЕМІУМ AI\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{fl.generate_message_link(message)}\n\n{(message.text or 'Медіа')[:800]}",
                        )
                        return
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"ПРЕМІУМ\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{fl.generate_message_link(message)}\n\n{(message.text or 'Медіа')[:800]}",
                )

        else:
            if message.text and rus_language == 1:
                if fl.rus_language(message.text):
                    await safe_delete(message)
                    asyncio.create_task(
                        send_timed_msg(
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
            fl.get_chat_settings.cache_invalidate(db, c_id)
            logger.warning(f":Додано новий чат\n{message.chat.title} ({c_id})")
        except Exception as e:
            logger.error(
                f"Помилка при отриманні ід власника {e}\nймовірно в бота поки що недостатньо прав\n{e}"
            )

            return


####
async def main() -> None:
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    async with aiosqlite.connect("anti_spam.db") as db:
        await fl.load_hashes(db)
        await dp.start_polling(
            bot,
            db=db,
            allowed_updates=[
                "message",
                "edited_message",
                "chat_member",
                "callback_query",
                "message_reaction",
            ],
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
