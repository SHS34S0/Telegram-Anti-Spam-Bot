import asyncio
import sys
import time
import aiosqlite
import config
import re

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
            f"Заблоковано {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГруппа {message.chat.title} {message.chat.id}"
        )
        await fl.send_remote_log(message, config.help_token, config.root, "BAN USER")
    except Exception as e:
        # Ловимо помилки (наприклад, бот не адмін)
        logger.error(
            f"Помилка {e} блокування користувача {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГруппа {message.chat.title} {message.chat.id}"
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
            f"МУТ {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГруппа {message.chat.title} {message.chat.id}"
        )
        await fl.send_remote_log(message, config.help_token, config.root, "MUTE USER")

    except Exception as e:
        logger.error(
            f"Помилка {e} при спроби замутити користувача {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГруппа {message.chat.title} {message.chat.id}"
        )
        await fl.send_remote_log(
            message, config.help_token, config.root, "Помилка під час муту користувача"
        )


async def send_timed_msg(bot, chat_id, text, delay=60):
    try:
        msg = await bot.send_message(chat_id=chat_id, text=text)
        await asyncio.sleep(delay)
        await safe_delete(msg)
    except Exception:
        pass


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
                        f"Помилка {e} при спробі видалити повідомлення через реакцію 🤡 від користувача {user_full_name} ({u_id})\nГруппа {reaction.chat.title} ({c_id})"
                    )
                return
    # ==========================================================
    if await fl.msg_count(db, u_id, c_id):
        return
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

    # ставить реакці. чи забирає ?
    if not reaction.new_reaction:
        return
    dc_number = await fl.check_dc_number(bot, u_id)
    if dc_number == 100:
        await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
        logger.warning(
            f"Заблоковано {user_full_name} {u_id}\nГруппа {reaction.chat.title} {c_id} \nПричина: Reaction Spam"
        )

        asyncio.create_task(
            send_timed_msg(bot, c_id, msg.SpamMessage.reaction_spam(user_full_name))
        )
        await root.user_info(
            bot,
            c_id,
            u_id,
            user_full_name,
            reaction.chat.title,
            "Reaction Spam фото в базі\n💖🎀💖🎀💖🎀💖🎀💖🎀💖🎀💖🎀💖🎀💖🎀",
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
    if message.new_chat_members or message.left_chat_member:
        return
    ####################
    u_id = message.from_user.id
    username = message.from_user.username  # username може не бути
    user_full_name = message.from_user.full_name
    c_id = message.chat.id
    chat_name = message.chat.title or "Особисті повідомлення"
    settings = await fl.get_chat_settings(db, c_id)
    ############# check alternativ
    asyncio.create_task(send_timed_msg(bot, c_id, msg.PromtAI.SYSTEM_SPAM_PROMPT))

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
            elif message.is_automatic_forward:  # репост з каналу який привязаний
                return
            # якщо код тут, то це спамер або хтось бажае бути анонімним
            await safe_delete(message)
            return
        ## Перевірк на шлюхосимволи
        if message.text and fl.has_weird_chars(message.text):
            await safe_delete(message)  # Безпечне видалення
            await safe_ban(message, u_id)
            await root.user_info(
                bot,
                c_id,
                u_id,
                user_full_name,
                chat_name,
                f"Шлюхосимвол\n\n{message.text[:800]}",
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
            except Exception:
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
                except Exception:
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
            #######################################################################
            if message.chat.username:
                # Публічні чати
                msg_link = f"https://t.me/{message.chat.username}/{message.message_id}"
            else:
                # Закриті чати та супергрупи
                clean_chat_id = str(message.chat.id).replace("-100", "", 1)
                msg_link = f"https://t.me/c/{clean_chat_id}/{message.message_id}"
            ########################################################################
            if await fl.check_user_bio(bot, u_id):
                try:
                    if dc_number in [1, 5]:
                        await safe_mute(message, u_id)
                        asyncio.create_task(
                            send_timed_msg(
                                bot, c_id, msg.SpamMessage.spam_18(user_full_name)
                            )
                        )
                        await safe_delete(message)
                    await root.user_info(
                        bot,
                        c_id,
                        u_id,
                        user_full_name,
                        chat_name,
                        f"Посилання в біо\n⛔️⛔️⛔️⛔️⛔️⛔️\nDC {dc_number}\n{msg_link}\n\n{message.text[:800]}",
                    )
                except Exception as e:
                    logger.error(
                        f"Помилка {e} при спроби замутити користувача {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГруппа {message.chat.title} {message.chat.id}"
                    )
                return
            avatar = await fl.check_user_avatar(bot, message.from_user.id)
            if avatar:
                try:
                    if dc_number in [1, 5]:
                        await safe_mute(message, u_id)
                        asyncio.create_task(
                            send_timed_msg(
                                bot, c_id, msg.SpamMessage.spam_18(user_full_name)
                            )
                        )
                        await safe_delete(message)

                    await root.user_info(
                        bot,
                        c_id,
                        u_id,
                        user_full_name,
                        chat_name,
                        f"Фото\nn⛔️⛔️⛔️⛔️⛔️⛔️\nDC {dc_number}\n{msg_link}\n\n{message.text[:800]}",
                    )
                except Exception as e:
                    logger.error(
                        f"Помилка {e} при спроби замутити користувача {message.from_user.first_name} {message.from_user.username} {message.from_user.id}\nГруппа {message.chat.title} {message.chat.id}"
                    )
                return
            # але спам ДС обмежимо
            if dc_number in [1, 5] and not message.from_user.is_bot:
                await safe_mute(message, u_id)
                await safe_delete(message)
                asyncio.create_task(
                    send_timed_msg(bot, c_id, msg.SpamMessage.mute(user_full_name))
                )
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"DC {dc_number}\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{msg_link}\n\n{message.text[:800]}",
                )
                return

            if message.from_user.is_premium and u_id > 7700000000:
                ################################################################################
                if message.text:
                    if await fl.is_spam(message.text):
                        # винести функціею показала гуд
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
                            f"ПРЕМІУМ AI\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{msg_link}\n\n{(message.text or 'Медіа')[:800]}",
                        )
                        return

                chat_info = await bot.get_chat(u_id)
                bio = chat_info.bio
                if bio:
                    pattern = r"(?:сторис|истории|прогноз|100%|кэф|₽|сторисе|экспресс|коэф|Бесплатный|бесплатный)"

                    if re.search(pattern, bio):
                        await safe_delete(message)
                        await safe_ban(message, u_id)
                        asyncio.create_task(
                            send_timed_msg(
                                bot, c_id, msg.SpamMessage.spam_18(user_full_name)
                            )
                        )
                ###################################################################################
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    f"ПРЕМІУМ\n🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫\n{msg_link}\n\n{(message.text or 'Медіа')[:800]}",
                )

            # else:
            #     if voting_buttons == 5:
            #         work_m_id = await message.reply(
            #             "⚠️ Чи виглядає це повідомлення підозрілим?\nПроголосуйте нижче 👇",
            #             reply_markup=get_vote_keyboard(),
            #         )
            #         # записуємо в базу данних ТИМЧАСОВИЙ запис на період голосування. передаємо необхідну інфу
            #         await db.execute(
            #             "INSERT OR IGNORE INTO votings (chat_id, message_id, user_id, work_m_id) VALUES (?, ?, ?, ?)",
            #             (c_id, message.message_id, u_id, work_m_id.message_id),
            #         )
            #         await db.commit()

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
    else:  # Схоже нас щойно додали в цей чяат треба запис в базу створити
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


##################################
def get_vote_keyboard():
    builder = InlineKeyboardBuilder()

    builder.add(
        InlineKeyboardButton(text="🤖 Бот", callback_data="vote_bot"),
        InlineKeyboardButton(text="👤 Не бот", callback_data="vote_human"),
    )

    builder.adjust(2)
    return builder.as_markup()  # Повертаємо готовий результат


@dp.callback_query(F.data.startswith("vote_"))
async def handle_voting(callback: CallbackQuery, db: aiosqlite.Connection):
    # якщо прибираю не працюе і кнопки завичаю. ТРЕБА ДОСЛІДИТИ
    await callback.answer("Дякуємо!", show_alert=True)

    voter_id = callback.from_user.id
    m_id = callback.message.message_id
    vote_result = callback.data
    c = await db.cursor()
    # перевірка чи перший раз голосує
    first_voiting = await fl.voting(db, m_id, voter_id)

    ###########################
    if vote_result == "vote_bot":
        if first_voiting:  # голосує вперше файл логу створено
            await db.execute(
                "UPDATE votings SET bot = bot + 1 WHERE work_m_id = ?",
                (m_id,),
            )
            await db.commit()
            # перевірка кількості голосів
            await c.execute(
                "SELECT * FROM votings WHERE work_m_id = ?",
                (m_id,),
            )
            ban = await c.fetchone()
            if not ban:
                await callback.answer("Голосування завершено.")
                return
            #################
            elif ban[4] >= VOITS:
                try:
                    # повідомлення де спам
                    await fl.clear_voting(db, m_id)
                    await callback.bot.delete_message(chat_id=ban[0], message_id=ban[1])
                except Exception:
                    pass
                await safe_ban(callback.message, ban[2], BAN24)
                # запит в базу, щоб дістати ім'я спамера
                await c.execute(
                    "SELECT name FROM users_global WHERE user_id = ?", (ban[2],)
                )
                spammer_data = await c.fetchone()
                # Якщо раптом імені нема в базі, то ставимо заглушку, щоб код не впав
                spammer_name = spammer_data[0] if spammer_data else "Спамер"
                # текст з правильним ід та іменем
                log_text = f'Користувачі вирішили, що <a href="tg://user?id={ban[2]}">{spammer_name}</a> 🤖 Бот.'
                # Інформативне повідомлення для історії змін в чаті буде відображатись остання редакція. закадаємо туди інфу про спамера
                await fl.clear_voting(db, m_id)
                await callback.message.edit_text(
                    log_text,
                    reply_markup=get_vote_keyboard(),
                )

                async def _wait_kill():
                    await asyncio.sleep(60)  # Чекаємо 60 сек
                    await safe_delete(callback.message)

                asyncio.create_task(_wait_kill())
            elif ban[5] >= VOITS:  # людина
                await fl.clear_voting(db, m_id)
                await callback.message.delete()

            else:
                await callback.message.edit_text(
                    f"⚠️ Чи виглядає це повідомлення підозрілим?\nПроголосуйте нижче 👇\n🤖 Бот: {ban[4]} ❌ 🧑 Людина: {ban[5]}",
                    reply_markup=get_vote_keyboard(),
                )
        else:
            await callback.answer("Ваш голос вже було зараховано", show_alert=True)
    elif vote_result == "vote_human":
        if not first_voiting:
            await callback.answer("Ваш голос вже було зараховано", show_alert=True)
            return
        # 1. Додаємо голос за людину
        await db.execute(
            "UPDATE votings SET human = human + 1 WHERE work_m_id = ?", (m_id,)
        )
        await db.commit()

        # Перевіряємо, скільки вже голосів
        await c.execute(
            "SELECT * FROM votings WHERE work_m_id = ?",
            (m_id,),
        )
        ban = await c.fetchone()

        if ban and ban[5] >= VOITS:  # Якщо 3 голоси за людину
            await fl.clear_voting(db, m_id)
            await safe_delete(callback.message)
        elif ban:
            # Оновлюємо текст, щоб бачити прогрес і в "людських" голосах
            await callback.message.edit_text(
                f"⚠️ Чи виглядає це повідомлення підозрілим?\nПроголосуйте нижче 👇\n🤖 Бот: {ban[4]} ❌ 🧑 Людина: {ban[5]}",
                reply_markup=get_vote_keyboard(),
            )
    else:
        pass
        # поки що так


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
