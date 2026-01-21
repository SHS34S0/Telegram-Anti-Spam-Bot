import aiosqlite
import re


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


async def get_chat_settings(db, c_id):  # преевірка хто є канал чату (повертаємо id)
    c = await db.cursor()
    await c.execute(
        "SELECT channel_id, owner_id, voting_buttons, rus_language, stop_word FROM chat_links WHERE chat_id = ?",
        (c_id,),
    )
    respond = await c.fetchone()
    if respond:  # знайшли канал ід
        return respond
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


def emoji_checker(message):
    ALLOWED = set(
        "абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!?,. "
    )
    try:
        total_len = len(message)

        if total_len < 25:
            return 100  # Малі повідомлення не чіпаємо

        clean_count = 0
        for char in message:
            if char in ALLOWED:
                clean_count += 1

        ratio = (clean_count * 100) / total_len

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
    except TypeError:  # все ок це не текст а гівка чи ще щось
        return 100


from aiogram import Bot


async def get_channel_owner(bot: Bot, channel_id: int):
    try:
        # список адмінів
        admins = await bot.get_chat_administrators(chat_id=channel_id)
        for admin in admins:
            if admin.status == "creator":
                return admin.user.id

    except Exception as e:
        print(f"Помилка {channel_id}: {e}")

    return None
