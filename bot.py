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

TOKEN = config.TOKEN
VOITS = 2
BAN24 = 86400
ADMIN_STATUSES = {"administrator", "creator"}
GOOD_STATUSES = {"member", "administrator", "creator"}
##########################################################


async def old_member(db, u_id, channel_id):
    await db.execute(
        "INSERT OR IGNORE INTO chat_stats (user_id, channel_id) VALUES (?, ?)",
        (u_id, channel_id),
    )
    await db.commit()


async def register_or_update_passport(db, user_id, full_name, username):
    await db.execute(
        "INSERT OR IGNORE INTO users_global (user_id, name, username) VALUES (?, ?, ?)",
        (user_id, full_name, username),
    )
    # Цей апдейт потрібен, щоб оновлювати зміну імені
    await db.execute(
        "UPDATE users_global SET name = ?, username = ? WHERE user_id = ?",
        (full_name, username, user_id),
    )
    await db.commit()


async def tandem_id(db, c_id):  # преевірка хто є канал чату (повертаємо id)
    c = await db.cursor()
    await c.execute("SELECT channel_id FROM chat_links WHERE chat_id = ?", (c_id,))
    channel_id = await c.fetchone()
    if channel_id:  # знайшли канал ід
        return channel_id[0]
    return None


# перевірка чи в базі є запис як підписник
async def check_sub(db, user_id, channel_id):
    c = await db.cursor()
    await c.execute(
        "SELECT * FROM chat_stats WHERE user_id = ? AND channel_id = ?",
        (user_id, channel_id),
    )
    check_status = await c.fetchone()
    if check_status:  # Якщо є в базі як підписник каналу
        return check_status is not None


def has_weird_chars(text):
    # Шукаємо специфічні символи
    weird_pattern = r"[ʜᴋᴀᴏʙʏɪᴍɴʟᴜꜰᴇᴘ]"
    if re.search(weird_pattern, text, re.IGNORECASE):
        return True
    return False


###### перевіряємо чи підписаний хочаб 2 хв
# можливо якщо ще десь буду використовувати треба час в хв передавати як аргумент.
# поки не чіпати
async def check_join_date(db, user_id, channel_id):
    c = await db.cursor()  # 1. Створили курсор
    await c.execute(  # Виконали запит через ЦЕЙ курсор
        "SELECT * FROM chat_stats WHERE user_id = ? AND channel_id = ? AND join_date >= datetime('now', '-2 minutes')",
        (user_id, channel_id),
    )
    result = await c.fetchone()  # Дістали результат
    return result is not None


##########
async def voting(db, m_id, voter_id):
    try:  # Пробуємо додати запис про голос
        await db.execute(
            "INSERT INTO votes_log (voting_m_id, voter_id) VALUES (?, ?)",
            (m_id, voter_id),
        )  # UNIQUE SQL
        await db.commit()  # Якщо ми тут юзер голосує вперше
        return True
    except aiosqlite.IntegrityError:  # якщо двічі голосуватиме
        return False


async def clear_voting(db, m_id):
    await db.execute("DELETE FROM votings WHERE work_m_id = ?", (m_id,))
    await db.execute("DELETE FROM votes_log WHERE voting_m_id = ?", (m_id,))
    await db.commit()


async def emoji_checker(message):
    ALLOWED = set(
        "абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!?,. "
    )

    total_len = len(message)
    if total_len < 25:
        return 100  # Малі повідомлення не чіпаємо

    clean_count = 0
    for char in message:
        if char in ALLOWED:
            clean_count += 1

    ratio = (clean_count * 100) / total_len

    # ДИНАМІЧНА ЛОГІКА
    # Якщо повідомлення короткедо 100 символів
    if total_len < 100:
        if ratio >= 60:  # Дозволяємо більше смайлів
            return 100
        else:
            return ratio  # Повертаємо реальний низький бал

    # Якщо повідомлення довге > 100
    else:
        if ratio >= 85:  # Вимагаємо чистоти
            return 100
        else:
            return ratio


########################################

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
    channel_id = await tandem_id(db, c_id)
    if not channel_id:  # пара не була знайдена
        # значить c_id = event.chat.id отримав ід каналу
        channel_id = c_id

    print(f"Юзер {user_id} ({full_name}) вступив у канал {channel_id}")

    await register_or_update_passport(db, user_id, full_name, username)
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
    await message.answer(f"Hello, {html.bold(message.from_user.full_name)}!")


############
@dp.message()
async def echo_handler(message: Message, bot: Bot, db: aiosqlite.Connection) -> None:
    async def safe_delete(message):
        """Видаляє повідомлення. Якщо його вже нема то просто мовчить."""
        try:
            await message.delete()
        except Exception:
            pass

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
    channel_id = await tandem_id(db, c_id)

    # emoji spam
    kef = await emoji_checker(message.text)

    # 75% тексту - це нормально для живого спілкування
    # Твій код перевірки
    if kef >= 90:
        pass

    elif kef >= 70:
        # Безпечне видалення
        await safe_delete(message)
        try:
            await message.chat.ban(user_id=u_id, until_date=int(time.time()) + BAN24)
            return
        except Exception:
            pass

    else:
        # Безпечне видалення
        await safe_delete(message)
        # Бан назавжди
        try:
            await message.chat.ban(user_id=u_id)
            return
        except Exception:
            pass

        # Банимо назавжди в випадку помилки
        await message.chat.ban(user_id=u_id)
        return

    ## Перевірк на шлюхосимволи
    if message.text and has_weird_chars(message.text):
        try:
            await message.delete()
            await message.chat.ban(user_id=u_id)
            return  # Зупиняємо все інше
        except Exception:
            return
    # превірка посилань та гіперпосилань
    bad_types = {"mention", "url", "text_link"}
    if message.entities and any(e.type in bad_types for e in message.entities):
        try:  # Якщо було спрацювання
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
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    return  # Чат чистий, далі не йдемо
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass
            return  # Чат чистий, далі не йдемо

    ###################початок
    # Запис або оновлення паспорта
    await register_or_update_passport(db, u_id, user_full_name, username)

    #################---------------------------------------------------------------------------перевірка чи підписник каналу
    # якщо channel_id не існує це не страшно. це ситуація коли бота в канал щойно додали.
    # він створить пару першим повідомленням в чаті. і з другого воно буде спрацьовувати
    if channel_id:  #  ід пару отрималои робимо далі преевірки
        # перевірка чи є в базі як підписник каналу ?
        status = await check_sub(db, u_id, channel_id)
        if status:
            await db.execute(
                "UPDATE chat_stats SET msg_count = msg_count + 1 WHERE user_id = ? AND channel_id = ?",
                (u_id, channel_id),  # передаємо обидва параметри
            )
            await db.commit()
            # після +1 до повідомлення починаємо преевірки

            # термін протягом якого підписаний користувач на канал.
            is_young = await check_join_date(db, u_id, channel_id)  # SQL

            if is_young:
                has_media = (
                    message.video_note
                    or message.sticker
                    or message.animation
                    or message.forward_date
                )
                if has_media:
                    # Бан 24 години
                    await message.delete()
                    await message.chat.ban(
                        user_id=u_id, until_date=int(time.time()) + BAN24
                    )
                    return  # рештиа не має сенсу
                else:
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
                    pass
            else:
                print("Перевірка пройдена: підписаний довше ніж 2 хв")
                # тут з часм варто додати персоналізовані функції для кожного каналу.
                # після створення адмін кабінету
                pass
        else:  # в базі нема запису про підписку на канал чи чат
            # Запит в тг чи підписаний НА КАНАЛ
            member = await bot.get_chat_member(
                chat_id=channel_id, user_id=message.from_user.id
            )
            if member.status in GOOD_STATUSES:
                # Підписаний вже в базі (значить старічок база дасть дефолтну дату приеднання з минулого)
                await old_member(db, u_id, channel_id)
            else:  # перевірка підписки на ЧАТ
                member = await bot.get_chat_member(
                    chat_id=c_id, user_id=message.from_user.id
                )
                if member.status in GOOD_STATUSES:
                    await old_member(db, u_id, channel_id)
                else:
                    print("Не підписаний взагалі ніде")
                    # я не впевнений чи це можливо враховуючи обмеження телеграму

    else:  # спрацюе коли нема пари. новий чат.
        # Отримуємо повну інформацію про чат, де написали повідомлення
        chat_info = await bot.get_chat(message.chat.id)

        # Перевіряємо, чи є прив'язаний канал
        linked_id = chat_info.linked_chat_id

        if linked_id:  # якщо отримали ід створюемо пару в базу
            c = await db.cursor()
            await c.execute(
                # Додаємо OR IGNORE сюди:
                "INSERT OR IGNORE INTO chat_links (chat_id, channel_id) VALUES (?, ?)",
                (c_id, int(linked_id)),
            )
            await db.commit()
        else:
            print(
                "ТРЕБА ПРОДУМАТИ ПОМИЛКУ КОЛИ НЕМА ПОВЯЗАНОГО КАНАЛУ. АБО ТОДІ ЧАТ І Є ГОЛОВНИМ"
            )

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
    first_voiting = await voting(db, m_id, voter_id)

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
                    await clear_voting(db, m_id)
                    await callback.bot.delete_message(chat_id=ban[0], message_id=ban[1])
                except Exception:
                    # Якщо повідомлення вже видалив адмін
                    # перевіряємо чи забанений. якщо так вихід якщо ні то бан і вихід
                    pass
                # сюди потрапляємо якщо адмін ще не встиг втрутитись
                await callback.message.chat.ban(
                    user_id=ban[2], until_date=int(time.time()) + BAN24
                )
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
                await clear_voting(db, m_id)
                await callback.message.edit_text(
                    log_text,
                    reply_markup=get_vote_keyboard(),
                )
                await callback.message.delete()
                # варто дописати чистку сміття з бази після голосування
            elif ban[5] >= VOITS:  # людина
                await clear_voting(db, m_id)
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
            await clear_voting(db, m_id)
            await callback.message.delete()
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
