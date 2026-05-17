import logging
import time
from collections import Counter

from pympler import asizeof

from aiogram import Bot, F, Router
import aiosqlite
import filters as fl
import utils
from database import db_manager
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
stats = Counter()
START_TIME = time.time()


def _format_uptime() -> str:
    delta = int(time.time() - START_TIME)
    days, remainder = divmod(delta, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days} д {hours} год {minutes} хв"
    if hours:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв {seconds} с"


def _format_bytes(size: int) -> str:
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f} МБ"
    if size >= 1024:
        return f"{size / 1024:.1f} КБ"
    return f"{size} Б"


def _hit_rate(ci) -> str:
    total = ci.hits + ci.misses
    return f"{ci.hits / total * 100:.0f}%" if total else "—"


def _get_proc_info() -> dict:
    fields = {"VmRSS", "VmPeak", "VmHWM", "VmSwap", "Threads", "FDSize"}
    result = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                key = line.split(":")[0]
                if key in fields:
                    parts = line.split()
                    # lines with kB: ["VmRSS:", "187432", "kB"]
                    # lines without: ["Threads:", "3"]
                    value = int(parts[1])
                    result[key] = _format_bytes(value * 1024) if len(parts) == 3 else str(value)
    except Exception:
        pass
    return result


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

        logger.warning(f"Starting mass unban for user {user_id} in {len(all_chats)} chats")
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
            except Exception as e:
                logger.warning(f"Restrict failed in chat {target_chat_id}: {e}")
                if "chat not found" in str(e) or "bot was kicked" in str(e):
                    dead_chat_reason = str(e)

            # Step 2: unban only if actually banned (safe for non-banned users)
            try:
                await bot.unban_chat_member(
                    chat_id=target_chat_id,
                    user_id=user_id,
                    only_if_banned=True,
                )
            except Exception as e:
                logger.warning(f"Unban failed in chat {target_chat_id}: {e}")
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
                logger.warning(f"Removed dead chat {target_chat_id} from DB: {dead_chat_reason}")

    except Exception as e:
        logger.warning(f"Error in mass_unban for user {user_id}: {e}")


async def mass_blocking(bot, db, user_id, ignore_chat_id):
    try:
        async with db.execute(
            "SELECT chat_id FROM chat_links WHERE chat_id != ? AND chat_id LIKE '-100%'",
            (ignore_chat_id,),
        ) as cursor:
            all_chats = await cursor.fetchall()

        if not all_chats:
            return

        logger.warning(f"Starting mass ban for user {user_id} in {len(all_chats)} chats")
        for row in all_chats:
            await asyncio.sleep(0.9)
            target_chat_id = row[0]  # rows are tuples like [(123,), (456,)]
            try:
                await bot.ban_chat_member(chat_id=target_chat_id, user_id=user_id)
            except Exception as e:
                logger.warning(f"Failed to ban {user_id} in chat {target_chat_id}: {e}")
                if "chat not found" in str(e) or "bot was kicked" in str(e):
                    await db.execute(
                        "DELETE FROM chat_links WHERE chat_id = ?", (target_chat_id,)
                    )
                    await db.commit()
                    logger.warning(f"Removed dead chat {target_chat_id} from DB: {e}")
    except Exception as e:
        logger.warning(f"Error in mass_blocking for user {user_id}: {e}")


def _get_phash_str(bio):
    return str(imagehash.phash(Image.open(bio)))


async def user_info(
    bot, c_id, u_id, user_full_name, chat_name, text, message_id: int | None = None
):
    photos = await bot.get_user_profile_photos(u_id, limit=1)

    if not photos.total_count:
        await bot.send_message(
            chat_id=str(config.root),
            text=f"⚠️ <a href='tg://user?id={u_id}'>{user_full_name}</a>\nФільтр: {text}\n(Фото профілю відсутнє)",
            parse_mode="HTML",
            reply_markup=moder_menu(u_id),
        )
        fl.SUSPICIOUS_USERS.add(u_id)
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
        await utils.delete_user_history(bot, u_id)

        # Delete the message that triggered this alert
        if message_id:
            try:
                await bot.delete_message(chat_id=c_id, message_id=message_id)
            except Exception as e:
                logger.warning(f"Auto-ban: failed to delete message {message_id}: {e}")

        # Ban user in the current chat immediately
        try:
            await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
        except Exception as e:
            logger.warning(f"Auto-ban: failed to ban {u_id} in {c_id}: {e}")

        await bot.send_message(
            chat_id=str(config.root),
            text=f"🚫 <a href='tg://user?id={u_id}'>{user_full_name}</a> — авто-бан (повторне спрацювання)",
            parse_mode="HTML",
            reply_markup=moder_menu(u_id, photo_phash),
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


def moder_menu(user_id, photo_hash=None):
    builder = InlineKeyboardBuilder()

    builder.add(
        InlineKeyboardButton(
            text="Bot", callback_data=f"black_list:{user_id}", style="danger"
        )
    )

    if photo_hash is not None:
        builder.add(
            InlineKeyboardButton(
                text=f"📷 Додати фото",
                callback_data=f"add_photo:{user_id}:{photo_hash}",
            )
        )
    builder.add(
        InlineKeyboardButton(
            text="Human", callback_data=f"unblock:{user_id}", style="success"
        )
    )
    builder.add(
        InlineKeyboardButton(text="Skip", callback_data=f"skip_suspect:{user_id}")
    )

    builder.adjust(3, 1)
    return builder.as_markup()  # Повертаємо готовий результат


########################################################################3
root_router = Router()
root_router.message.filter(F.chat.type == "private")


@root_router.message()
async def root_info(message: Message, bot: Bot):
    db = await db_manager.get_db()
    c_id = message.chat.id
    if c_id == config.root:
        user_full_name = message.from_user.full_name
        chat_name = message.chat.title or "Особисті повідомлення"
        if message.text and message.text.isdigit():
            fl.GLOBAL_BANNED.add(int(message.text))
            await utils.delete_user_history(bot, int(message.text))
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
            ci_chat = fl.get_chat_settings.cache_info()
            ci_msg = fl.msg_count.cache_info()
            ci_dc = fl.check_dc_number.cache_info()
            await bot.send_message(
                chat_id=str(config.root),
                text=(
                    f"💾 <b>Кеш (alru_cache):</b>\n\n"
                    f"  chat_settings: <b>{ci_chat.currsize}</b> / {ci_chat.maxsize} зап. | ⚡ <b>{_hit_rate(ci_chat)}</b> ({ci_chat.hits}↑ {ci_chat.misses}↓)\n"
                    f"  msg_count: <b>{ci_msg.currsize}</b> / {ci_msg.maxsize} зап. | ⚡ <b>{_hit_rate(ci_msg)}</b> ({ci_msg.hits}↑ {ci_msg.misses}↓)\n"
                    f"  check_dc: <b>{ci_dc.currsize}</b> / {ci_dc.maxsize} зап. | ⚡ <b>{_hit_rate(ci_dc)}</b> ({ci_dc.hits}↑ {ci_dc.misses}↓)"
                ),
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
                text=f"📊 Список активних чатів з моменту перезавантаження:\n⏱ Час роботи: <b>{_format_uptime()}</b>\n\n{chats_text}",
                parse_mode="HTML",
            )
        if message.text and message.text.lower() == "mem":
            p = _get_proc_info()
            msg_total = sum(
                len(msgs)
                for chats in fl.MSG_HISTORY.values()
                for msgs in chats.values()
            )
            swap_line = f"  Swap: <b>{p.get('VmSwap', 'н/д')}</b>\n" if p.get("VmSwap", "0 Б") != "0 Б" else ""
            await bot.send_message(
                chat_id=str(config.root),
                text=(
                    f"🧠 <b>Пам'ять процесу</b>  ⏱ {_format_uptime()}\n"
                    f"  Зараз (RSS): <b>{p.get('VmRSS', 'н/д')}</b>\n"
                    f"  Пік (HWM):   <b>{p.get('VmHWM', 'н/д')}</b>\n"
                    f"  Пік (Peak):  <b>{p.get('VmPeak', 'н/д')}</b>\n"
                    f"{swap_line}"
                    f"  Потоки: <b>{p.get('Threads', 'н/д')}</b>  |  "
                    f"FD: <b>{p.get('FDSize', 'н/д')}</b>\n\n"
                    f"📦 <b>Структури:</b>\n"
                    f"  GLOBAL_BANNED: <b>{len(fl.GLOBAL_BANNED)}</b> зап. — {_format_bytes(asizeof.asizeof(fl.GLOBAL_BANNED))}\n"
                    f"  PHOTO_HASH: <b>{len(fl.PHOTO_HASH)}</b> зап. — {_format_bytes(asizeof.asizeof(fl.PHOTO_HASH))}\n"
                    f"  MSG_HISTORY: <b>{len(fl.MSG_HISTORY)}</b> юз. / <b>{msg_total}</b> пов. — {_format_bytes(asizeof.asizeof(fl.MSG_HISTORY))}\n"
                    f"  REACTION_HISTORY: <b>{len(fl.REACTION_HISTORY)}</b> юз. — {_format_bytes(asizeof.asizeof(fl.REACTION_HISTORY))}\n"
                    f"  SUSPICIOUS_USERS: <b>{len(fl.SUSPICIOUS_USERS)}</b> зап. — {_format_bytes(asizeof.asizeof(fl.SUSPICIOUS_USERS))}\n"
                    f"  LINKS_HISTORY: <b>{len(fl.LINKS_HISTORY)}</b> зап. — {_format_bytes(asizeof.asizeof(fl.LINKS_HISTORY))}\n"
                    f"  PASSPORT_HASHES: <b>{len(fl.PASSPORT_HASHES)}</b> зап. — {_format_bytes(asizeof.asizeof(fl.PASSPORT_HASHES))}\n\n"
                    f"💾 <b>Кеш (alru_cache):</b>\n"
                    f"  msg_count: <b>{fl.msg_count.cache_info().currsize}</b> зап. — {_format_bytes(asizeof.asizeof(getattr(fl.msg_count, '_LRUCacheWrapper__cache', {})))}\n"
                    f"  chat_settings: <b>{fl.get_chat_settings.cache_info().currsize}</b> зап. — {_format_bytes(asizeof.asizeof(getattr(fl.get_chat_settings, '_LRUCacheWrapper__cache', {})))}\n"
                    f"  check_dc: <b>{fl.check_dc_number.cache_info().currsize}</b> зап. — {_format_bytes(asizeof.asizeof(getattr(fl.check_dc_number, '_LRUCacheWrapper__cache', {})))}"
                ),
                parse_mode="HTML",
            )
        if message.text and message.text.lower() in ["stats", "stat", "statistics"]:
            await bot.send_message(
                chat_id=str(config.root),
                text=(
                    f"📊 <b>Статистика з моменту перезапуску</b>\n"
                    f"⏱ Час роботи: <b>{_format_uptime()}</b>\n\n"
                    f"🚫 <b>Дії:</b>\n"
                    f"  Банів: <b>{stats['total ban']}</b>\n"
                    f"  Мутів: <b>{stats['total mute']}</b>\n"
                    f"  Видалено повідомлень: <b>{stats['total delete messages']}</b>\n\n"
                    f"🔍 <b>Причини спрацювання:</b>\n"
                    f"  Глобальний чорний список: <b>{stats['global ban']}</b>\n"
                    f"  Підозрілі символи: <b>{stats['bad chars']}</b>\n"
                    f"  Стоп канал: <b>{stats['stop channel']}</b>\n"
                    f"  Номер карти: <b>{stats['card numbers']}</b>\n"
                    f"  Емодзі спам: <b>{stats['emoji checker']}</b>\n"
                    f"  Посилання: <b>{stats['stop links']}</b>\n"
                    f"  Хеш фото: <b>{stats['found hash']}</b>\n"
                    f"  Поганий DC: <b>{stats['bad dc']}</b>\n"
                    f"  Погане біо: <b>{stats['bad bio']}</b>\n"
                    f"  Преміум AI: <b>{stats['premium work']}</b>"
                ),
                parse_mode="HTML",
            )
        return


@root_router.callback_query(
    F.data.startswith(
        (
            "black_list:",
            "unblock:",
            "add_photo:",
            "skip_suspect:",
        )
    )
)
async def admin_settings(callback: CallbackQuery, bot: Bot):
    db = await db_manager.get_db()
    list_data = callback.data
    value = list_data.split(":")[1]
    result = list_data.split(":")[0]
    if result.startswith("black_list"):
        fl.GLOBAL_BANNED.add(int(value))
        await utils.delete_user_history(bot, int(value))
        # status 1 is ban
        await fl.change_user_status(int(value), 1)
        await callback.answer(f"✅ Додано в чорний список", show_alert=True)
    elif result in ("unblock", "skip_suspect"):
        fl.GLOBAL_BANNED.discard(int(value))
        fl.SUSPICIOUS_USERS.discard(int(value))  # type: ignore[attr-defined]
        await fl.change_user_status(int(value), 0)
        if result == "unblock":
            await callback.answer("Відправляю запит зняття обмежень", show_alert=True)
            await mass_unban(bot, db, int(value), 111)
        else:
            await callback.answer(
                "✅ Юзера прибрано зі списку підозрюваних та чорного списку",
                show_alert=True,
            )

    elif result.startswith("add_photo"):
        parts = list_data.split(":")
        user_to_clear = int(parts[1])
        hash_value = parts[2]
        await db.execute(
            """
            INSERT INTO photo_hash (hash, last_seen) VALUES (?, CURRENT_TIMESTAMP)
            ON CONFLICT(hash) DO UPDATE SET last_seen = CURRENT_TIMESTAMP
            """,
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
            logger.warning(f"Failed to update photo hash dict: {e}")
            await callback.answer()
