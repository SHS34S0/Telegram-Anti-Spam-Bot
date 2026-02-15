import asyncio
import logging
import sys
import time
import re
from os import getenv
from datetime import datetime, timedelta

import aiosqlite
import config

from aiogram import Bot, Dispatcher, html, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER
from aiogram.types import (
    Message,
    ChatMemberUpdated,
    CallbackQuery,
    InlineKeyboardButton,
    ChatPermissions,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import MessageReactionUpdated
import filters as fl
import root

TOKEN = config.TOKEN
VOITS = 3
BAN24 = 86400
ADMIN_STATUSES = {"administrator", "creator"}
GOOD_STATUSES = {"member", "administrator", "creator"}


##########################################################


#################################
async def safe_delete(message):
    try:
        await message.delete()
    except Exception:
        pass


async def safe_ban(message, u_id, sec=0):
    try:
        if sec > 0:
            # Бан на час
            end_date = int(time.time()) + sec
            await message.chat.ban(user_id=u_id, until_date=end_date)
            print(f"TEMP BAN: {u_id} for {sec}s")
        else:
            # Бан назавжди
            await message.chat.ban(user_id=u_id)
            print(f"PERMA BAN: {u_id}")

    except Exception as e:
        # Ловимо помилки (наприклад, бот не адмін)
        print(f"Ban error: {e}")


async def safe_mute(message, u_id, sec=0):
    try:
        end_date = int(time.time()) + sec

        await message.bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=u_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=end_date,
        )

    except Exception as e:
        print(f"Mute error: {e}")


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
    if await fl.msg_count(db, u_id, c_id):
        return
    await db.execute(
        """
                INSERT INTO chat_stats (user_id, channel_id, msg_count, join_date) 
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, channel_id) 
                DO UPDATE SET msg_count = msg_count + 1
                """,
        (u_id, c_id),
    )
    await db.commit()

    # ставить реакці. чи забирає ?
    print("reactions")
    if not reaction.new_reaction:
        return
    reason_text = (
        f"🛡 Користувача <b>{user_full_name}</b> заблоковано (Бан).\n"
        f"⛔️ <b>Причина:</b> Reaction Spam.\n"
        f"📉 <i>З метою привернення уваги до профілю (реклама/18+).</i>"
    )
    dc_number = await fl.check_dc_number(bot, u_id)
    if dc_number in [1, 5]:
        await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
        asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
        await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    reaction.chat.title,
                    "Reaction Spam Problem DC",
                )
        return
    # if await fl.check_user_bio(bot, u_id):
    #     await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
    #     asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
    #     return

    if await fl.check_user_avatar(bot, u_id) == 100:
        await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
        asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
        await root.user_info(
            bot,
            c_id,
            u_id,
            user_full_name,
            reaction.chat.title,
            "Reaction Spam Avatar",
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
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, channel_id) DO UPDATE SET join_date = CURRENT_TIMESTAMP
        """,
        (user_id, c_id),
    )
    await db.commit()


#####
@dp.message(CommandStart())  # /start
async def command_start_handler(message: Message) -> None:
    text = f"👋 <b>Вітаю, {html.bold(message.from_user.full_name)}!</b>\n" + config.TEXT
    if message.chat.title == None:
        await message.answer(text)


############
@dp.message()
@dp.edited_message()
async def echo_handler(message: Message, bot: Bot, db: aiosqlite.Connection) -> None:

    if message.chat.id != -1001834041310:
        if message.sender_chat:
            if message.sender_chat.id == message.chat.id:
                return  # це адмін
            elif message.is_automatic_forward:  # репост з каналу який привязаний
                return
            # якщо код тут то це спамер або хтось бажае бути анонімним
            await safe_delete(message)
            return

    if message.new_chat_members or message.left_chat_member:
        return
    ####################
    u_id = message.from_user.id
    username = message.from_user.username  # username може не бути
    user_full_name = message.from_user.full_name
    c_id = message.chat.id
    content = message.text or message.caption
    chat_name = message.chat.title or "Особисті повідомлення"
    settings = await fl.get_chat_settings(db, c_id)
    print(f"📊 КЕШ каналів: {fl.get_chat_settings.cache_info()}")
    reason_text_ban_18 = (
        f"‼️ Користувач {user_full_name} заблоковано.\nПричина: ⛔️ Спам 18+."
    )

    reason_mute = (
        f"🤐 Користувач <b>{user_full_name}</b> тимчасово переведений у режим читання (Мут).\n"
        f"⚠️ <b>Причина:</b> Підозра на недопустимий контент (18+).\n"
        f"⏳ <i>Обмеження буде знято після ручної перевірки адміністратором.</i>"
    )

    if message.chat.title == None and str(message.from_user.id) == str(config.root):
        await fl.mass_blocking(bot, db, int(message.text), 111)
        await root.user_info(
            bot,
            c_id,
            int(message.text),
            user_full_name,
            chat_name,
            "Ручне блокування по ІД",
        )
        return

    if settings:
        owner_id, voting_buttons, rus_language, stop_word = settings
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
                "Шлюхосимвол",
            )
            asyncio.create_task(send_timed_msg(bot, c_id, reason_text_ban_18))
            # массове блокування у всіх доступних чатах авансом
            await fl.mass_blocking(bot, db, u_id, c_id)
            return
        if message.text and fl.check_card(message.text):
            reason_text = f'⚠️ <a href="tg://user?id={u_id}">{user_full_name}</a> ваше повідомлення видалено.\nПричина: Номер картки без узгодження з адмінами.'
            try:  # Якщо було спрацювання
                member_chat = await bot.get_chat_member(
                    chat_id=c_id, user_id=message.from_user.id
                )
                if member_chat.status in ADMIN_STATUSES:
                    pass  # все ок адмінам можна
                else:
                    await safe_delete(message)
                    asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
                    return  # Чат чистий, далі не йдемо
            except Exception:
                await safe_delete(message)
                asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
                return  # Чат чистий, далі не йдемо
        if message.text:
            kef = fl.emoji_checker(message.text)
            reas_text = f"‼️ Користувач {user_full_name} заблоковано.\nПричина: 🚫 Рекламний спам."
            if kef >= 90:
                pass
            elif kef >= 70:
                await safe_delete(message)
                await safe_ban(message, u_id, BAN24)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    "emoji checker",
                )
                asyncio.create_task(send_timed_msg(bot, c_id, reas_text))
                return
            else:
                await safe_delete(message)
                # Бан назавжди
                await safe_ban(message, u_id)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    "emoji checker",
                )
                asyncio.create_task(send_timed_msg(bot, c_id, reas_text))
                return

        bad_types = {"mention", "url", "text_link"}
        if message.entities and any(e.type in bad_types for e in message.entities):
            reason_text = f'⚠️ <a href="tg://user?id={u_id}">{user_full_name}</a> посилання в цьому чаті заборонені.'
            try:  # Якщо було спрацювання
                member_chat = await bot.get_chat_member(
                    chat_id=c_id, user_id=message.from_user.id
                )
                if member_chat.status in ADMIN_STATUSES:
                    pass  # все ок адмінам можна
                else:
                    await safe_delete(message)
                    asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
                    return  # Чат чистий, далі не йдемо
            except Exception:
                await safe_delete(message)
                asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
                return  # Чат чистий, далі не йдемо

        ###################
        # Запис або оновлення паспорта
        await fl.register_or_update_passport(db, u_id, user_full_name, username)
        # перевірка чи є в базі як підписник каналу ?
        print(f"📊 КЕШ учасників: {fl.msg_count.cache_info()}")
        if not await fl.msg_count(db, u_id, c_id):
            await db.execute(
                """
                        INSERT INTO chat_stats (user_id, channel_id, msg_count, join_date) 
                        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                        ON CONFLICT(user_id, channel_id) 
                        DO UPDATE SET msg_count = msg_count + 1
                        """,
                (u_id, c_id),
            )
            await db.commit()
            fl.msg_count.cache_invalidate(db, u_id, c_id)
            print(f"📊 КЕШ DC: {fl.check_dc_number.cache_info()}")
            dc_number = await fl.check_dc_number(bot, u_id)
            print(f"📊 КЕШ Біо: {fl.check_user_bio.cache_info()}")
            if await fl.check_user_bio(bot, u_id):
                try:
                    if dc_number in [1, 5]:
                        await safe_ban(message, u_id)
                        await fl.mass_blocking(bot, db, u_id, c_id)
                        asyncio.create_task(
                            send_timed_msg(bot, c_id, reason_text_ban_18)
                        )
                    else:
                        await safe_mute(message, u_id)
                        asyncio.create_task(send_timed_msg(bot, c_id, reason_mute))
                    await safe_delete(message)
                    await root.user_info(
                        bot,
                        c_id,
                        u_id,
                        user_full_name,
                        chat_name,
                        "Посилання в біо",
                    )
                except Exception as e:
                    print(
                        f"Помилка {e}\nймовірно ми намагались замутити адміна і не змогли"
                    )
                return
            # треба зробити щоб сюда не спішив код а дочекався результату вище для єкономії ресурсу
            print(f"📊 КЕШ Фото: {fl.check_user_avatar.cache_info()}")
            avatar = await fl.check_user_avatar(bot, message.from_user.id)
            if avatar:
                try:
                    if avatar == 50:
                        if dc_number in [1, 5]:
                            await safe_ban(message, u_id)
                            await fl.mass_blocking(bot, db, u_id, c_id)
                            asyncio.create_task(
                                send_timed_msg(bot, c_id, reason_text_ban_18)
                            )
                        else:  # ДС 2 3 4
                            await safe_mute(message, u_id)
                            asyncio.create_task(send_timed_msg(bot, c_id, reason_mute))
                    else:  # порно
                        await safe_ban(message, u_id)
                        await fl.mass_blocking(bot, db, u_id, c_id)
                        asyncio.create_task(
                            send_timed_msg(bot, c_id, reason_text_ban_18)
                        )

                    await safe_delete(message)
                    await root.user_info(
                        bot,
                        c_id,
                        u_id,
                        user_full_name,
                        chat_name,
                        "Фото",
                    )
                except Exception as e:
                    print(
                        f"Помилка {e}\nймовірно ми намагались замутити адміна і не змогли"
                    )
                    ###########################
                    #################################
                return
            print("Перевірка аватару успішна")
            # але спам ДС обмежимо
            if dc_number in [1, 5]:
                await safe_mute(message, u_id)
                await safe_delete(message)
                asyncio.create_task(send_timed_msg(bot, c_id, reason_mute))
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    "Проблемний ДС",
                )
                # тут буде круто кнопка я не бот на 1 хв якщо преевірки пройшов а ДС стрьомний

            # тимчасово тут для наповнення списку новими суфіксами вручну
            if dc_number not in [1, 2, 4, 5, None]:
                info_text = (
                    f'⚠️ <a href="tg://user?id={u_id}">{user_full_name}</a>\n'
                    f'Чат: "{chat_name}\n'
                    f"Avatar hash: <code>{dc_number}</code>"
                )
                await bot.send_message(
                    chat_id=str(config.root),
                    text=f"\n{info_text}",
                    parse_mode="HTML",
                )

            has_media = message.video_note or message.forward_date
            if has_media:
                reason_text = f"‼️ Користувач {user_full_name} заблоковано.\nПричина: 🚫 Рекламний спам."
                await safe_delete(message)
                await safe_ban(message, u_id, BAN24)
                await root.user_info(
                    bot,
                    c_id,
                    u_id,
                    user_full_name,
                    chat_name,
                    "Переслані повідомлення",
                )
                asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
                return  # рештиа не має сенсу

            else:
                if voting_buttons == 5:
                    work_m_id = await message.reply(
                        "⚠️ Чи виглядає це повідомлення підозрілим?\nПроголосуйте нижче 👇",
                        reply_markup=get_vote_keyboard(),
                    )
                    # записуємо в базу данних ТИМЧАСОВИЙ запис на період голосування. передаємо необхідну інфу
                    await db.execute(
                        "INSERT OR IGNORE INTO votings (chat_id, message_id, user_id, work_m_id) VALUES (?, ?, ?, ?)",
                        (c_id, message.message_id, u_id, work_m_id.message_id),
                    )
                    await db.commit()

        else:
            print("Перевірка на новачка пройдена")
            if message.text and rus_language == 1:

                reason_text = f"🛡 {user_full_name}, я видалив ваше повідомлення, оскільки в цьому чаті не пишуть російською. "
                status = fl.rus_language(message.text)
                if status == 50:
                    await safe_delete(message)
                    asyncio.create_task(send_timed_msg(bot, c_id, reason_text))

            # тут будуть функції які адмін може вмикати вимикати
            # rus
            # stop words
    else:  # Схоже нас щойно додали в цей чяат треба запис в базу створити
        print("Треба додати нові чати канали")
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
        except Exception as e:
            print(
                f"Помилка при отриманні ід власника {e}\nймовірно в бота поки що недостатньо прав"
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
    # треба налагодити бо щоб не натиснув висвічуеться тільки це
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
                print("ban")
                try:
                    # повідомлення де спам
                    await fl.clear_voting(db, m_id)
                    await callback.bot.delete_message(chat_id=ban[0], message_id=ban[1])
                except Exception:
                    pass
                await safe_ban(callback.message, ban[2], BAN24)
                # запит в базу, щоб дістати імя спамера
                await c.execute(
                    "SELECT name FROM users_global WHERE user_id = ?", (ban[2],)
                )
                spammer_data = await c.fetchone()
                # Якщо раптом імені нема в базі то ставимо заглушку, щоб код не впав
                spammer_name = spammer_data[0] if spammer_data else "Спамер"
                # текст з правильним ід та іменем
                log_text = f'Користувачі вирішили, що <a href="tg://user?id={ban[2]}">{spammer_name}</a> 🤖 Бот.'
                # інформативне повідомлення для історії змін в чаті буде відображатись остання редакція. закадаємо туди інфу про спамера
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
