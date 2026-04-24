import logging

from aiogram import Bot, F, Router
import aiosqlite
import filters as fl
import io
import asyncio
import imagehash
from PIL import Image

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    ChatPermissions,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config

chats_info = {}

logger = logging.getLogger(__name__)


async def mass_unban(bot, db, user_id, ignore_chat_id):
    # All permissions enabled used to restore a muted user
    full_permissions = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=False,
        can_invite_users=True,
        can_pin_messages=False,
    )

    try:
        async with db.execute(
            "SELECT chat_id FROM chat_links WHERE chat_id != ? AND chat_id LIKE '-100%'",
            (ignore_chat_id,),
        ) as cursor:
            all_chats = await cursor.fetchall()

        if not all_chats:
            return

        print(f"Починаю розбан/розмут юзера {user_id} у {len(all_chats)} чатах...")
        for row in all_chats:
            await asyncio.sleep(0.9)
            target_chat_id = row[0]  # rows are tuples like [(123,), (456,)]
            dead_chat_reason = None  # set if chat is gone or bot was kicked

            # Step 1: try to unmute (restore permissions). Fails if user is banned — that's ok.
            try:
                await bot.restrict_chat_member(
                    chat_id=target_chat_id,
                    user_id=user_id,
                    permissions=full_permissions,
                )
                print(f"Розмучено в чаті {target_chat_id}")
            except Exception as e:
                print(f"restrict не вдалось {target_chat_id}: {e}")
                if "chat not found" in str(e) or "bot was kicked" in str(e):
                    dead_chat_reason = str(e)

            # Step 2: unban only if actually banned (safe for non-banned users)
            try:
                await bot.unban_chat_member(
                    chat_id=target_chat_id,
                    user_id=user_id,
                    only_if_banned=True,
                )
                print(f"Розбанено в чаті {target_chat_id}")
            except Exception as e:
                print(f"unban не вдалось {target_chat_id}: {e}")
                if dead_chat_reason is None and (
                    "chat not found" in str(e) or "bot was kicked" in str(e)
                ):
                    dead_chat_reason = str(e)

            # Remove chat from DB if it no longer exists or bot was kicked
            if dead_chat_reason:
                await db.execute(
                    "DELETE FROM chat_links WHERE chat_id = ?", (target_chat_id,)
                )
                await db.commit()
                print(f"Видалено чат {target_chat_id} з бази: {dead_chat_reason}")

    except Exception as e:
        print(f"Помилка при розблокуванні: {e}")


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
            target_chat_id = row[0]  # rows are tuples like [(123,), (456,)]
            try:
                await bot.ban_chat_member(chat_id=target_chat_id, user_id=user_id)
                print(f"Забанено в чаті {target_chat_id}")
            except Exception as e:
                print(f"Не вдалось забанити в {target_chat_id}: {e}")
                if "chat not found" in str(e) or "bot was kicked" in str(e):
                    await db.execute(
                        "DELETE FROM chat_links WHERE chat_id = ?", (target_chat_id,)
                    )
                    await db.commit()
                    print(f"Видалено чат {target_chat_id} з бази: {str(e)}")
    except Exception as e:
        print(f"Помилка в mass_blocking: {e}")


def _get_phash_str(bio):
    return str(imagehash.phash(Image.open(bio)))


async def user_info(
    bot, c_id, u_id, user_full_name, chat_name, text, message_id: int | None = None
):
    photos = await bot.get_user_profile_photos(u_id, limit=1)

    # Якщо фото немає — відправляємо текст і одразу виходимо (return)
    # з часом потрібно преевірити чи є це проблема не додати в чорний список підозрюваного без фото
    if not photos.total_count:
        await bot.send_message(
            chat_id=str(config.root),
            text=f"⚠️ <a href='tg://user?id={u_id}'>{user_full_name}</a>\nФільтр: {text}\n(Фото профілю відсутнє)",
            parse_mode="HTML",
        )
        return

    # Якщо фото є, йдемо далі без зайвих відступів
    photo = photos.photos[0][-1]
    # Якщо фото в базі нам звіт не потрібен
    if await fl.check_hash(bot, photo):
        return
    photo_file_id = photo.file_id
    suffix = photo.file_unique_id[-3:]

    # Завантаження та генерація phash
    file = await bot.get_file(photo_file_id)
    bio = io.BytesIO()
    await bot.download_file(file.file_path, bio)
    bio.seek(0)

    loop = asyncio.get_running_loop()
    photo_phash = await loop.run_in_executor(None, _get_phash_str, bio)

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

    # Second alert for same user = auto-ban without sending photo again
    if u_id in fl.SUSPICIOUS_USERS:
        logger.warning(
            f"Користувач вдруге засвітився як підозрілий {c_id}, {u_id}, {user_full_name}\n {text}"
        )
        fl.SUSPICIOUS_USERS.discard(int(u_id))  # type: ignore[attr-defined]
        fl.GLOBAL_BANNED.add(u_id)

        # Delete the message that triggered this alert
        if message_id:
            try:
                await bot.delete_message(chat_id=c_id, message_id=message_id)
            except Exception as e:
                print(f"Auto-ban: failed to delete message {message_id}: {e}")

        # Ban user in the current chat immediately
        try:
            await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
        except Exception as e:
            print(f"Auto-ban: failed to ban {u_id} in {c_id}: {e}")

        await bot.send_message(
            chat_id=str(config.root),
            text=f"🚫 <a href='tg://user?id={u_id}'>{user_full_name}</a> — авто-бан (повторне спрацювання)",
            parse_mode="HTML",
        )
        return

    # First alert — remember the user and send photo for manual review
    fl.SUSPICIOUS_USERS.add(u_id)

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
            text="Bot", callback_data=f"black_list:{user_id}", style="danger"
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
        if message.text and message.text.isdigit():
            fl.GLOBAL_BANNED.add(int(message.text))
            await mass_blocking(bot, db, int(message.text), 111)

            await user_info(
                bot,
                c_id,
                int(message.text),
                user_full_name,
                chat_name,
                "Ручне блокування по ІД",
            )
        if message.text and message.text.lower() == "cache":
            await bot.send_message(
                chat_id=str(config.root),
                text=f"📊 КЕШ каналів: {fl.get_chat_settings.cache_info()}\n📊 КЕШ учасників: {fl.msg_count.cache_info()}\n📊 КЕШ DC: {fl.check_dc_number.cache_info()}",
                parse_mode="HTML",
            )
        if message.text and message.text.lower() == "chats":
            chats_text = ""
            for index, chat in enumerate(chats_info.items(), start=1):
                c_id = chat[0]
                clean_c_id = (
                    str(c_id).replace("-100", "", 1)
                    if str(c_id).startswith("-100")
                    else str(c_id)
                )
                chat_name = chat[1]
                chats_text += (
                    f'{index} <a href="https://t.me/c/{clean_c_id}">{chat_name}</a>\n'
                )
            await bot.send_message(
                chat_id=str(config.root),
                text=f"📊 Список активних чатів з моменту перезавантаження:\n\n{chats_text}",
                parse_mode="HTML",
            )

        return


@root_router.callback_query(
    F.data.startswith(
        (
            "black_list:",
            "unblock:",
            "add_photo:",
        )
    )
)
async def admin_settings(callback: CallbackQuery, bot: Bot, db: aiosqlite.Connection):
    list_data = callback.data
    value = list_data.split(":")[1]
    result = list_data.split(":")[0]
    if result.startswith("black_list"):
        fl.GLOBAL_BANNED.add(int(value))
        # status 1 is ban
        await fl.change_user_status(db, int(value), 1)
        await callback.answer(f"✅ Додано в чорний список", show_alert=True)
    elif result.startswith("unblock"):
        # на випадок коли не вручну банив і ід нема в чорному списку
        if int(value) in fl.GLOBAL_BANNED:
            fl.GLOBAL_BANNED.discard(int(value))
        if int(value) in fl.SUSPICIOUS_USERS:
            fl.SUSPICIOUS_USERS.discard(int(value))  # type: ignore[attr-defined]
        # status 0 is unban
        await callback.answer(f"Відправляю запит зняття обмежень", show_alert=True)
        await fl.change_user_status(db, int(value), 0)
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
            # скидаємо кеш в цій сесії для користувача
            fl.check_dc_number.cache_invalidate(bot, user_to_clear)
            # вікно
            await callback.answer(
                "✅ Фото додано в базу\nКеш юзера очищено!", show_alert=True
            )

        except Exception as e:
            print(f"Помилка оновлення словника: {e}")
            await callback.answer()
