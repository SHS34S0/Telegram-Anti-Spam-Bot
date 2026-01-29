import aiosqlite
import re
import os
from nudenet import NudeDetector
import asyncio
import time
import os
import asyncio
from nudenet import NudeDetector

# ініціалізація детектора
try:
    _nude_detector = NudeDetector()
except Exception as e:
    print(f"⚠️ Помилка запуску NudeNet: {e}")
    _nude_detector = None

# 0.60
BAN_LIST = {
    # гола шкіра
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "MALE_BREAST_EXPOSED",
    # замануха
    "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
    "FEMALE_GENITALIA_COVERED",
}


async def check_user_avatar(bot, user_id: int) -> bool:
    # Якщо детектор не запустився, пропускаємо юзера 
    if _nude_detector is None:
        return False

    file_path = f"temp_avatar_{user_id}.jpg"

    try:
        # взяти фото профілю
        photos = await bot.get_user_profile_photos(user_id, limit=1)

        # Якщо фото немає все ок
        if not photos.total_count:
            return False

        # останне фото
        photo_file_id = photos.photos[0][-1].file_id

        # скакачати файл
        file = await bot.get_file(photo_file_id)
        await bot.download_file(file.file_path, file_path)

        # Отримуємо поточний цикл подій
        loop = asyncio.get_running_loop()
        # Запускаємо в окремому потоці
        detections = await loop.run_in_executor(None, _nude_detector.detect, file_path)

        for item in detections:
            label = item["class"]
            score = item["score"]

            # Твій поріг 0.60
            if label in BAN_LIST and score > 0.60:
                return True  # БАН

    except Exception as e:
        print(f"Помилка перевірки аватара {user_id}: {e}")

    finally:
        # видалення файлу
        if os.path.exists(file_path):
            os.remove(file_path)

    return False


######################


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


def emoji_checker(text):
    ALLOWED = set(
        "абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!?,. "
    )
    try:
        total_len = len(text)

        if total_len < 25:
            return 100  # Малі повідомлення не чіпаємо

        clean_count = 0
        for char in text:
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


async def check_user_bio(bot, user_id):
    try:
        chat_info = await bot.get_chat(user_id)
        bio = chat_info.bio

        if not bio:
            return False  # Біо немає - все ок

        # всі посилання
        # link_pattern = r"(https?://|www\.|t\.me/|[a-zA-Z0-9-]+\.[a-zA-Z]{2,})"
        # Ловить тільки посилання на ТГ
        link_pattern = r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/"

        if re.search(link_pattern, bio):
            return True  # Знайшли сміття

    except Exception:
        pass  # Якщо не вдалось отримати профіль - не банимо

    return False  # Все чисто


async def mass_blocking(bot, db, user_id, ignore_chat_id):
    try:
        async with db.execute(
            "SELECT chat_id FROM chat_links WHERE chat_id != ?", (ignore_chat_id,)
        ) as cursor:
            all_chats = await cursor.fetchall()

        if not all_chats:
            return

        print(f"Починаю мас-бан юзера {user_id} у {len(all_chats)} чатах...")
        for row in all_chats:
            target_chat_id = row[
                0
            ]  # Результат це список кортежів [(123,), (456,)], беремо [0]
            try:
                await bot.ban_chat_member(chat_id=target_chat_id, user_id=user_id)
                print(f"Забанено в чаті {target_chat_id}")
            except Exception as e:
                print(f"Не вдалось забанити в {target_chat_id}: {e}")
    except Exception as e:
        print(f"Помилка в mass_blocking: {e}")


######################################
