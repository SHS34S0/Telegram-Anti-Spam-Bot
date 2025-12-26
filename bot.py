import config
import asyncio
import logging
import sys
from os import getenv
import aiosqlite
from aiogram import Bot
from aiogram import Bot, Dispatcher, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram import Router, types
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER
from aiogram import F
from aiogram.types import ChatMemberUpdated
import re
from aiogram.exceptions import TelegramBadRequest
from datetime import datetime, timedelta
import time

TOKEN = config.TOKEN
##########################################################


async def tandem_id(db, c_id):  # преевірка хто є канал чату (повертаємо id)
    c = await db.cursor()
    await c.execute("SELECT channel_id FROM chat_links WHERE chat_id = ?", (c_id,))
    channel_id = await c.fetchone()
    if channel_id:
        return channel_id[0]
    else:
        return None


async def check_sub(db, user_id, channel_id):
    c = await db.cursor()
    await c.execute(
        "SELECT * FROM chat_stats WHERE user_id = ? AND channel_id = ?",
        (user_id, channel_id),
    )
    check_status = await c.fetchone()
    if check_status:  # Якщо є в базі як підписник каналу
        return True
    else:  # Якщо нема як підписник каналу в базі
        return False


def has_weird_chars(text):
    # Шукаємо специфічні символи
    weird_pattern = r"[ʜᴋᴀᴏʙʏɪᴍɴʟᴜꜰᴇᴘ]"
    if re.search(weird_pattern, text, re.IGNORECASE):
        return True
    return False


######
async def check_join_date(db, user_id, channel_id):
    c = await db.cursor()  # 1. Створили курсор
    await c.execute(  # 2. Виконали запит через ЦЕЙ курсор
        "SELECT * FROM chat_stats WHERE user_id = ? AND channel_id = ? AND join_date >= datetime('now', '-2 minutes')",
        (user_id, channel_id),
    )
    result = await c.fetchone()  # 3. Дістали результат
    return result is not None
    # if result:
    #     return True
    # else:
    #     return False


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
        # значить c_id має ід каналу
        channel_id = c_id

    print(f"Юзер {user_id} ({full_name}) вступив у канал {channel_id}")

    await db.execute(
        "INSERT OR IGNORE INTO users_global (user_id, name, username) VALUES (?, ?, ?)",
        (user_id, full_name, username),
    )
    await db.execute(
        """
        INSERT INTO chat_stats (user_id, channel_id, join_date) 
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, channel_id) DO UPDATE SET join_date = CURRENT_TIMESTAMP
        """,
        (user_id, channel_id),
    )
    await db.commit()


# Замість INSERT OR IGNORE для статистики



#####
@dp.message(CommandStart())  # /start
async def command_start_handler(message: Message) -> None:
    await message.answer(f"Hello, {html.bold(message.from_user.full_name)}!")


############
@dp.message()
async def echo_handler(message: Message, bot: Bot, db: aiosqlite.Connection) -> None:
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
            if member_chat.status in ["administrator", "creator"]:
                pass  # все ок адмінам можна
            else:
                member = await bot.get_chat_member(
                    chat_id=channel_id, user_id=message.from_user.id
                )
                if member.status in ["administrator", "creator"]:
                    pass
                else:
                    await message.delete()
                    return  # Чат чистий, далі не йдемо
        except Exception:
            await message.delete()
            return  # Чат чистий, далі не йдемо

    ###################початок
    # Запис або оновлення паспорта
    # INSERT OR IGNORE додасть юзера якщо його ще нема в базі
    await db.execute(
        "INSERT OR IGNORE INTO users_global (user_id, name, username) VALUES (?, ?, ?)",
        (u_id, user_full_name, username),
    )
    # UPDATE оновить імя якщо юзер його змінив (спрацюєОСІНТ тригер в базі)
    await db.execute(
        "UPDATE users_global SET name = ?, username = ? WHERE user_id = ?",
        (user_full_name, username, u_id),
    )
    await db.commit()

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
            is_young = await check_join_date(db, u_id, channel_id)

            if is_young:
                if u_id > 6999999999:
                    # Бан 24 години
                    ban_until = int(time.time()) + 86400  # Надійніше через Unix-час
                    await message.delete()
                    await message.chat.ban(user_id=u_id, until_date=ban_until)
                    print("Занадто молодий (7млрд+): бан 24 години")
                    return  # рештиа не має сенсу
                else:
                    # Бан 1 година
                    ban_until = int(time.time()) + 3600
                    await message.delete()
                    await message.chat.ban(user_id=u_id, until_date=ban_until)
                    print("Занадто молодий (звичайний): бан 1 година")
                    return  # рештиа не має сенсу
            else:
                print("Перевірка пройдена: підписаний довше ніж 2 хв")
                pass
        else:  # в базі нема
            # Запит в тг чи підписаний НА КАНАЛ а не чат
            member = await bot.get_chat_member(
                chat_id=channel_id, user_id=message.from_user.id
            )
            if member.status in ["member", "administrator", "creator"]:
                # Підписаний аде не в базі (значить старічок база дасть дефолтну дату приеднання з минулого)
                c = await db.cursor()
                await c.execute(
                    "INSERT OR IGNORE INTO chat_stats (user_id, channel_id) VALUES (?, ?)",
                    (u_id, channel_id),
                )
                await db.commit()
                # запуск АНТИСПАМ ФУНКЦІЙ словники ітд
                # по часу не преевіряємо бо старічок

            else:  # не підписаний на канал і чат ?????
                # поки не впевнений але оновлена логіка не має сюди взагалі завести. треба пізніше преевірити
                print("Не підписаний на канал взагалі")

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


async def main() -> None:
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    async with aiosqlite.connect("anti_spam.db") as db:
        # Додай параметр allowed_updates, щоб отримувати події вступу/виходу
        await dp.start_polling(bot, db=db, allowed_updates=["message", "chat_member"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
