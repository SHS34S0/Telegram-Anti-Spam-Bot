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
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
import filters as fl

TOKEN = config.TOKEN
VOITS = 3
BAN24 = 86400
ADMIN_STATUSES = {"administrator", "creator"}
GOOD_STATUSES = {"member", "administrator", "creator"}


##########################################################
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


# обробка вступу
@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> MEMBER))
async def on_user_join(event: ChatMemberUpdated, db: aiosqlite.Connection):
    # Отримуємо ID каналу або чату куди вступили
    c_id = event.chat.id
    # Отримуємо ID користувача хто вступив
    user_id = event.new_chat_member.user.id
    # Отримуємо ім'я для паспорта
    full_name = event.new_chat_member.user.full_name
    username = event.new_chat_member.user.username  # Може бути None

    # Якщо вступ був в чат ми шукаемо пару каналу ід і повертаємо канал ід
    # якщо вступ був в канал ми не знайдемо пару
    settings = await fl.get_chat_settings(db, c_id)
    if settings:  # unpaking
        channel_id, owner_id, voting_buttons, rus_language, stop_word = settings
    else:  # нема запису про канал чи ще щось. спочатку варто створитизапис в базу
        return

    if not channel_id:  # пара не була знайдена
        # значить c_id = event.chat.id отримав ід каналу
        channel_id = c_id

    print(f"Юзер {user_id} ({full_name}) вступив у канал {channel_id}")

    await fl.register_or_update_passport(db, user_id, full_name, username)
    await db.execute(
        """
        INSERT INTO chat_stats (user_id, channel_id, join_date) 
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, channel_id) DO UPDATE SET join_date = CURRENT_TIMESTAMP
        """,
        (user_id, channel_id),
    )
    await db.commit()
    # Замінити на INSERT OR IGNORE для статистики ?


#####
@dp.message(CommandStart())  # /start
async def command_start_handler(message: Message) -> None:
    text = f"👋 <b>Вітаю, {html.bold(message.from_user.full_name)}!</b>\n" + config.TEXT
    if message.chat.title == None:
        await message.answer(text)


############
@dp.message()
async def echo_handler(message: Message, bot: Bot, db: aiosqlite.Connection) -> None:

    #########################################3
    # тут може міститись помилка. оскільки підтверджено бот пропускає написи від імені каналу не того який бот адмінить.
    if message.sender_chat:
        return  # Це пише канал або анонімний адмін, не чіпаємо його
    if message.new_chat_members or message.left_chat_member:
        return

    ####################
    # Одразу витягуємо id
    u_id = message.from_user.id
    username = message.from_user.username  # username може не бути
    user_full_name = message.from_user.full_name
    c_id = message.chat.id
    chat_name = message.chat.title or "Особисті повідомлення"
    settings = await fl.get_chat_settings(db, c_id)
    if settings:
        channel_id, owner_id, voting_buttons, rus_language, stop_word = settings
        ## Перевірк на шлюхосимволи
        if message.text and fl.has_weird_chars(message.text):
            reason_text = f"🛡 Користувач {user_full_name} більше не покаже свій 🍑"
            await safe_delete(message)  # Безпечне видалення
            await safe_ban(message, u_id)
            asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
            return

        kef = fl.emoji_checker(message.text)
        reas_text = f"🛡 Користувач {user_full_name} був заблокований за спам."
        if kef >= 90:
            pass
        elif kef >= 70:
            await safe_delete(message)
            await safe_ban(message, u_id, BAN24)
            asyncio.create_task(send_timed_msg(bot, c_id, reas_text))
            return
        else:
            await safe_delete(message)
            # Бан назавжди
            await safe_ban(message, u_id)
            asyncio.create_task(send_timed_msg(bot, c_id, reas_text))
            return

        bad_types = {"mention", "url", "text_link"}
        if message.entities and any(e.type in bad_types for e in message.entities):
            try:  # Якщо було спрацювання
                reason_text = f'🛡 <a href="tg://user?id={u_id}">{user_full_name}</a> посилання заборонені'
                member_chat = await bot.get_chat_member(
                    chat_id=c_id, user_id=message.from_user.id
                )
                if member_chat.status in ADMIN_STATUSES:
                    pass  # все ок адмінам можна
                else:
                    member = await bot.get_chat_member(
                        chat_id=channel_id, user_id=message.from_user.id
                    )
                    if member.status in ADMIN_STATUSES:
                        pass
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
        status = await fl.check_sub(db, u_id, channel_id)
        if status:
            await db.execute(
                "UPDATE chat_stats SET msg_count = msg_count + 1 WHERE user_id = ? AND channel_id = ?",
                (u_id, channel_id),  # передаємо обидва параметри
            )
            await db.commit()
            # після +1 до повідомлення починаємо преевірки

            # термін протягом якого підписаний користувач на канал.
            is_young = await fl.check_join_date(db, u_id, channel_id)  # SQL

            if is_young:
                has_media = (
                    message.video_note
                    or message.sticker
                    or message.animation
                    or message.forward_date
                )
                if has_media:
                    reason_text = (
                        f"🛡 Користувач {user_full_name} був заблокований за спам."
                    )
                    await safe_delete(message)
                    await safe_ban(message, u_id, BAN24)
                    asyncio.create_task(send_timed_msg(bot, c_id, reason_text))
                    return  # рештиа не має сенсу
                else:
                    if voting_buttons == 0:
                        return
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
                print("Перевірка пройдена: підписаний довше ніж 2 хв")
            # тут будуть функції які адмін може вмикати вимикати

        else:  # в базі нема запису про підписку на канал чи чат
            # Запит в тг чи підписаний НА КАНАЛ
            member = await bot.get_chat_member(
                chat_id=channel_id, user_id=message.from_user.id
            )
            if member.status in GOOD_STATUSES:
                await fl.old_member(db, u_id, channel_id)
            else:  # перевірка підписки на ЧАТ
                member = await bot.get_chat_member(
                    chat_id=c_id, user_id=message.from_user.id
                )
                if member.status in GOOD_STATUSES:
                    await fl.old_member(db, u_id, channel_id)
                else:
                    print("Не підписаний взагалі ніде")
                    # я не впевнений чи це можливо враховуючи обмеження телеграму

    else:  # спрацюе коли нема пари. новий чат.
        # Отримуємо повну інформацію про чат, де написали повідомлення
        chat_info = await bot.get_chat(message.chat.id)

        # Перевіряємо, чи є прив'язаний канал
        linked_id = chat_info.linked_chat_id

        if linked_id:  # якщо отримали ід створюемо пару в базу
            try:
                real_owner_id = await fl.get_channel_owner(bot, linked_id)
                c = await db.cursor()
                await c.execute(
                    # Додаємо OR IGNORE сюди:
                    "INSERT OR IGNORE INTO chat_links (chat_id, channel_id, owner_id) VALUES (?, ?, ?)",
                    (c_id, int(linked_id), real_owner_id),
                )
                await db.commit()
            except Exception as e:
                print(
                    f"Помилка при отриманні ід власника {e}\nймовірно в бота недостатньо прав"
                )
                return
        else:
            # якщо код тут то ймовірно це просто чат без каналу. поки бот для таких не працює
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
            bot, db=db, allowed_updates=["message", "chat_member", "callback_query"]
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
