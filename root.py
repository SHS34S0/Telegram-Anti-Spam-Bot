import asyncio
import config
import filters as fl
from aiogram import Router, F
from aiogram.types import Message
from aiogram import Bot
from aiogram import Router, F
from aiogram import Bot, Dispatcher, html, F
from aiogram.filters import Command
from aiogram.types import Message
import aiosqlite
import filters as fl
import time
import io
import asyncio
import imagehash
from PIL import Image

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config


async def mass_unban(bot, db, user_id, ignore_chat_id):
    try:
        async with db.execute(
            "SELECT chat_id FROM chat_links WHERE chat_id != ? AND chat_id LIKE '-100%'",
            (ignore_chat_id,),
        ) as cursor:
            all_chats = await cursor.fetchall()

        if not all_chats:
            return

        print(f"Починаю розбан юзера {user_id} у {len(all_chats)} чатах...")
        for row in all_chats:
            await asyncio.sleep(0.9)
            target_chat_id = row[
                0
            ]  # Результат це список кортежів [(123,), (456,)], беремо [0]
            try:
                await bot.unban_chat_member(chat_id=target_chat_id, user_id=user_id)
                print(f"Розбанено в чаті {target_chat_id}")
            except Exception as e:
                print(f"Не вдалось розбанити {target_chat_id}: {e}")
    except Exception as e:
        print(f"Помилка при розблокуванні: {e}")


def _get_phash_str(bio):
    return str(imagehash.phash(Image.open(bio)))


async def user_info(bot, c_id, u_id, user_full_name, chat_name, text):
    photos = await bot.get_user_profile_photos(u_id, limit=1)

    # Якщо фото немає — відправляємо текст і одразу виходимо (return)
    if not photos.total_count:
        await bot.send_message(
            chat_id=str(config.root),
            text=f"⚠️ <a href='tg://user?id={u_id}'>{user_full_name}</a>\nФільтр: {text}\n(Фото профілю відсутнє)",
            parse_mode="HTML",
        )
        return

    # Якщо фото є, йдемо далі без зайвих відступів 
    photo = photos.photos[0][-1]
    photo_file_id = photo.file_id
    suffix = photo.file_unique_id[-3:]

    # Завантаження та генерація phash
    file = await bot.get_file(photo_file_id)
    bio = io.BytesIO()
    await bot.download_file(file.file_path, bio)
    bio.seek(0)

    loop = asyncio.get_running_loop()
    photo_phash = await loop.run_in_executor(None, _get_phash_str, bio)

    # suffix = photo.file_unique_id[-3:]
    # if fl.DC_DICT.get(suffix):
    #     code_hash = fl.DC_DICT.get(suffix)
    # code_hash = photo.file_unique_id

########

    # code_hash = "Невідомий DC"
    # if suffix in config.dc_5:
    #     code_hash = "DC 5"
    # elif suffix in config.dc_1:
    #     code_hash = "DC 1"
    # elif suffix in config.dc_2:
    #     code_hash = "DC 2"
    # elif suffix in config.dc_4:
    #     code_hash = "DC 4"
    clean_c_id = (
        str(c_id).replace("-100", "", 1) if str(c_id).startswith("-100") else str(c_id)
    )

    info_text = (
        f'⚠️ <a href="tg://user?id={u_id}">{user_full_name}</a>\n'
        f'Чат: <a href="https://t.me/c/{clean_c_id}">{chat_name}</a>\n'
        f"Suffix: <code>{suffix}</code>\n"
        f"Full hash: <code>{photo.file_unique_id}</code>\n"
        f"Фільтр: {text}"
    )

    await bot.send_photo(
        chat_id=str(config.root),
        photo=photo_file_id,
        caption=info_text,
        reply_markup=moder_menu(u_id, photo_phash),
        parse_mode="HTML",
    )

def moder_menu(user_id, photo_hash):
    builder = InlineKeyboardBuilder()

    builder.add(
        InlineKeyboardButton(
            text="Bot", callback_data=f"mass_blocking:{user_id}", style="danger"
        ),
        InlineKeyboardButton(
            text=f"📷 Додати фото", callback_data=f"add_photo:{user_id}:{photo_hash}"
        ),
        InlineKeyboardButton(
            text="Human", callback_data=f"unblock:{user_id}", style="success"
        ),
    )
    builder.adjust(3)
    return builder.as_markup()  # Повертаємо готовий результат


########################################################################3
root_router = Router()
root_router.message.filter(F.chat.type == "private")


@root_router.message()
async def root_info(message: Message, bot: Bot, db):
    c_id = message.chat.id
    if c_id == config.root:
        user_full_name = message.from_user.full_name
        chat_name = message.chat.title or "Особисті повідомлення"

        await fl.mass_blocking(bot, db, int(message.text), 111)

        await user_info(
            bot,
            c_id,
            int(message.text),
            user_full_name,
            chat_name,
            "Ручне блокування по ІД",
        )
        return


@root_router.callback_query(
    F.data.startswith(
        (
            "mass_blocking:",
            "unblock:",
            "add_photo:",
        )
    )
)
async def admin_settings(callback: CallbackQuery, bot: Bot, db: aiosqlite.Connection):

    list_data = callback.data
    value = list_data.split(":")[1]
    result = list_data.split(":")[0]
    if result.startswith("mass_blocking"):
        await callback.message.answer(f"Починаю массове блокування")
        await fl.mass_blocking(bot, db, int(value), 111)
    elif result.startswith("unblock"):
        await callback.message.answer(f"Відправляю запит зняття обмежень")
        await mass_unban(bot, db, int(value), 111)
    elif result.startswith("add_photo"):
        parts = list_data.split(":")
        user_to_clear = int(parts[1])
        hash_value = parts[2]
        await db.execute(
            "INSERT OR IGNORE INTO photo_hash (hash) VALUES (?)",
            (hash_value,),
        )
        await db.commit()

        try:
            new_hash_obj = imagehash.hex_to_hash(hash_value)
            fl.PHOTO_HASH[new_hash_obj] = True
            # скидаемо кеш в цій сессії для користувача
            fl.check_dc_number.cache_invalidate(bot, user_to_clear)
            # спливаюче вікно
            await callback.answer(
                "✅ Фото додано в базу\nКеш юзера очищено!", show_alert=True
            )

        except Exception as e:
            print(f"Помилка оновлення словника: {e}")
            await callback.answer(
            )
