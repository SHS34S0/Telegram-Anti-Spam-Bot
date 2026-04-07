import re
import asyncio
import os
from nudenet import NudeDetector  # type: ignore[import-untyped]
from async_lru import alru_cache
import json
import imagehash
import io
from PIL import Image
import aiosqlite
import aiohttp
import logging
import httpx
from config import HF_TOKEN, MODEL, API_URL, TIMEOUT
import messages as msg
from collections import deque
import time

logger = logging.getLogger(__name__)
#######################################################
with open("dc.json", "r", encoding="utf-8") as f:
    DC_DICT = json.load(f)
########################################################


THRESHOLD = 5
PHOTO_HASH = {}  # type: ignore[var-annotated]
LINKS_HISTORY = {}
GLOBAL_BANNED = set()
SUSPICIOUS_USERS = set()  # type: ignore[var-annotated]


async def load_banned_users(db):
    async with db.execute(
            "SELECT user_id FROM users_global WHERE status = 1"
    ) as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            GLOBAL_BANNED.add(int(row[0]))
        print(f"✅ Завантажено {len(GLOBAL_BANNED)} користувачів в чорний список")


async def load_hashes(db: aiosqlite.Connection):
    PHOTO_HASH.clear()  # Очищаємо перед завантаженням (на всякий випадок)
    async with db.execute("SELECT hash FROM photo_hash") as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            hash_text = row[0]
            PHOTO_HASH[imagehash.hex_to_hash(hash_text)] = True
    print(f"✅ Завантажено {len(PHOTO_HASH)} фото у словник фільтрів.")


##########################################################################
# ініціалізація детектора
try:
    _nude_detector = NudeDetector()
except Exception as er:
    logger.error(f"Помилка запуску {er}")
    _nude_detector = None
_nude_semaphore = asyncio.Semaphore(2)  # кількість потоків
# 0.60
BAN_LIST = {
    # гола шкіра
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "MALE_BREAST_EXPOSED",
}

MUTE_LIST = {
    "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
    "FEMALE_GENITALIA_COVERED",
}


@alru_cache(maxsize=50000)
async def check_user_avatar(bot, user_id: int):
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

        # останнє фото
        photo_file_id = photos.photos[0][-1].file_id

        # скачати файл
        file = await bot.get_file(photo_file_id)
        await bot.download_file(file.file_path, file_path)

        # Отримуємо поточний цикл подій
        loop = asyncio.get_running_loop()
        # Запускаємо в окремому потоці
        async with _nude_semaphore:
            detections = await loop.run_in_executor(
                None, _nude_detector.detect, file_path
            )

        for item in detections:
            label = item["class"]
            score = item["score"]

            if label in BAN_LIST and score > 0.60:
                return 100  # БАН
            if label in MUTE_LIST and score > 0.80:
                return 50  # МУТ

    except Exception as e:
        logger.error(f"Помилка перевірки аватара {user_id}: {e}")

    finally:
        # видалення файлу
        if os.path.exists(file_path):
            os.remove(file_path)

    return False


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


@alru_cache(maxsize=1000)
async def get_chat_settings(db, c_id):  # перевірка хто є канал чату (повертаємо id)
    c = await db.cursor()
    await c.execute(
        "SELECT owner_id, voting_buttons, rus_language, stop_word, stop_channel, stop_links, card_number, emoji_checker, reaction_spam FROM chat_links WHERE chat_id = ?",
        (c_id,),
    )
    respond = await c.fetchone()
    if respond:  # знайшли канал ід
        return respond
    return None


def has_weird_chars(text):
    # Шукаємо специфічні символи
    weird_pattern = r"[ʜᴋᴀᴏʙʏɪᴍɴʟᴜꜰᴇᴘ]"
    if re.search(weird_pattern, text, re.IGNORECASE):
        return True
    return False


@alru_cache(maxsize=50000)
async def msg_count(db, user_id, channel_id):
    c = await db.cursor()  # 1. Створили курсор
    await c.execute(  # Виконали запит через ЦЕЙ курсор
        "SELECT * FROM chat_stats WHERE user_id = ? AND channel_id = ? AND msg_count > 0",
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
    allowed = set(
        "абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯabcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!?,. "
    )
    try:
        total_len = len(text)

        if total_len < 25:
            return 100  # Малі повідомлення не чіпаємо

        clean_count = 0
        for char in text:
            if char in allowed:
                clean_count += 1

        ratio = (clean_count * 100) / total_len

        # Якщо повідомлення коротке до 100 символів
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
    except TypeError:  # все ок це не текст, а гіф чи ще щось
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


@alru_cache(maxsize=50000)
async def check_user_bio(bot, user_id):
    try:
        chat_info = await bot.get_chat(user_id)
        bio = chat_info.bio
        if not bio:
            return False  # Біо немає - все ок
        # https://t.me/+
        link_pattern = (
            r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/\+"
        )
        pattern = r"(сторис|истории|прогноз|100%|кэф|коэф|коэффициент|₽|сторисе|экспресс|бесплатный|прибыль|доход|заработок|канальчік|кохатися|секретик)"
        # priority
        if re.search(pattern, bio, re.IGNORECASE):
            return 100
        if re.search(link_pattern, bio):
            return True  # Знайшли сміття

    except Exception as e:
        logger.error(f"Проблема при отриманні біо {user_id}: {e}")
    # Якщо не вдалось отримати профіль не банимо

    return False  # Все чисто


# потрібно переробити на зняття мут чи блоку але без видалення з спільноти якщо мут
async def mass_blocking(bot, db, user_id, ignore_chat_id):
    try:
        async with db.execute(
                "SELECT chat_id FROM chat_links WHERE chat_id != ? AND chat_id LIKE '-100%'",
                (ignore_chat_id,),
        ) as cursor:
            all_chats = await cursor.fetchall()

        if not all_chats:
            return

        print(f"Починаю мас-бан юзера {user_id} у {len(all_chats)} чатах...")
        for row in all_chats:
            await asyncio.sleep(0.9)
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


def rus_language(text):
    for i in text.lower():
        if i in ["ы", "э", "ъ", "ё"]:
            return True
    words = {
        "что",
        "как",
        "или",
        "если",
        "почему",
        "вот",
        "только",
        "здесь",
        "сейчас",
        "теперь",
        "никогда",
        "очень",
        "когда",
        "где",
        "нет",
        "конечно",
        "наверное",
        "пожалуйста",
        "спасибо",
        "человек",
        "жизнь",
        "такой",
        "могу",
        "понимаю",
        "должен",
        "нужен",
        "говоря",
        "личку",
        "работа",
        "нужен",
        "каждую",
    }

    have = words & set(text.lower().split())
    if have:
        return True
    else:
        return False


def check_card(text):
    # Шукаємо 16 цифр, між якими не більше 3 нецифрових символів поспіль.
    pattern = r"\d(?:\D{0,3}\d){15}"
    for match in re.finditer(pattern, text):
        digits = re.sub(r"\D", "", match.group())
        if luhn_check(digits):
            return True
    return False


def luhn_check(card_number):
    sum_ = 0
    parity = len(card_number) % 2
    for i, digit in enumerate(card_number):
        digit = int(digit)
        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        sum_ += digit
    return sum_ % 10 == 0


# Виносимо важку математику в окрему звичайну функцію
def _calculate_phash(image_bytes):
    return imagehash.phash(Image.open(image_bytes))


# -------------------------------------------
async def check_hash(bot, photo):
    try:
        file = await bot.get_file(photo.file_id)

        photo_bytes = io.BytesIO()
        await bot.download_file(file.file_path, photo_bytes)
        photo_bytes.seek(0)

        # Запускаємо генерацію хешу БЕЗ блокування основного бота
        loop = asyncio.get_running_loop()
        new_hash = await loop.run_in_executor(None, _calculate_phash, photo_bytes)

        # Шукаємо збіг
        for saved_hash in PHOTO_HASH.keys():
            if new_hash - saved_hash <= THRESHOLD:
                logger.warning(f"HASH {saved_hash}")
                return True  # БАН

    except Exception as e:
        logger.error(f"Помилка перевірки хешу: {e}")
    return False


def massage_type_check(message):
    if message.text:
        return "text"
    elif message.photo:
        return "photo"
    elif message.sticker:
        return "sticker"
    elif message.animation:
        return "animation"
    elif message.video:
        return "video"
    elif message.document:
        return "document"
    else:
        return "other"


@alru_cache(maxsize=50000)
async def check_dc_number(bot, u_id):
    photos = await bot.get_user_profile_photos(u_id, limit=1)
    # практика показала так буде краще
    if photos.total_count == 0:
        await asyncio.sleep(5)
        photos = await bot.get_user_profile_photos(u_id, limit=1)

    if photos.total_count > 0:
        photo = photos.photos[0][-1]
        ##### Тут треба звіряти хеш іншою функцією.
        if await check_hash(bot, photo):
            return 100
        suffix = photo.file_unique_id[-3:]
        return DC_DICT.get(suffix) or photo.file_unique_id
    return None


def is_good_mention(entities, message):
    for e in entities:
        if e.type == "mention":
            mention_text = message[e.offset: e.offset + e.length]
            if mention_text.lower() == "@admin":
                return True
    return False


async def send_remote_log(message, logger_token, admin_id, text):
    user = message.from_user
    chat = message.chat

    msg_link = (
        message.get_url()
        if chat.type in ["supergroup", "channel"]
        else "ПП / Приватна група"
    )

    log_text = (
        f"🚨 <b>{text}</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 <b>Юзер:</b> {user.full_name} (<code>{user.id}</code>)\n"
        f"📍 <b>Чат:</b> {chat.title}\n"
        f"🔗 <a href='{msg_link}'>Посилання на пост</a>\n"
        f"📝 <b>Текст:</b> <code>{message.text or 'Медіа/Інше'}</code>"
    )

    # HTTP
    url = f"https://api.telegram.org/bot{logger_token}/sendMessage"
    payload = {
        "chat_id": admin_id,
        "text": log_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,  # Щоб бачити прев'ю посилання
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                return await response.json()
    except Exception as e:
        print(f"Помилка відправки через зовнішнього бота: {e}")


async def is_spam(message: str) -> bool:
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": msg.PromtAI.SYSTEM_SPAM_PROMPT},
            {"role": "user", "content": message},
        ],
        "max_tokens": 5,
        "temperature": 0.1,
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                API_URL, headers=headers, json=body, timeout=TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            answer = data["choices"][0]["message"]["content"].strip().upper()

            return "SPAM" in answer
        except Exception as e:
            logger.error(f"Помилка при спробі аналізувати повідомлення AI {e}")
            return False


def generate_message_link(message):
    if message.chat.username:
        # Публічні чати
        return f"https://t.me/{message.chat.username}/{message.message_id}"
    else:
        # Закриті чати та супергрупи
        clean_chat_id = str(message.chat.id).replace("-100", "", 1)
        return f"https://t.me/c/{clean_chat_id}/{message.message_id}"


def count_links(user_id, chat_id):
    now = time.time()
    if user_id not in LINKS_HISTORY:
        LINKS_HISTORY[user_id] = deque()

    LINKS_HISTORY[user_id].append(now)
    LINKS_HISTORY[user_id].append(chat_id)
    # 3 minutes
    while LINKS_HISTORY[user_id] and now - LINKS_HISTORY[user_id][0] > 180:
        LINKS_HISTORY[user_id].popleft()
        LINKS_HISTORY[user_id].popleft()
    # 3 messages = len 6
    if len(LINKS_HISTORY[user_id]) > 5:
        return True  # Mute
    return False


async def change_user_status(db, user_id, status: int):
    """Status 1 is ban or 0 unban"""
    try:
        await db.execute(
            "UPDATE users_global SET status = ? WHERE user_id = ?",
            (
                status,
                user_id,
            ),
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Проблема при зміні статуса користувача {user_id}\n{e}")


async def get_user_lifespan(db, user_id, chat_id):
    cursor = await db.execute(
        "SELECT join_date, (strftime('%s','now') - strftime('%s', join_date)) FROM chat_stats WHERE user_id = ? AND channel_id = ?",
        (user_id, chat_id),
    )
    seconds = await cursor.fetchone()
    return seconds[1]
