import asyncio
import logging
import time

import aiosqlite
from aiogram import Bot, F, Router
import filters as fl
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils import send_timed_msg

logger = logging.getLogger(__name__)

report_router = Router()

# Commands and mentions that trigger a report (must be a reply)
REPORT_TRIGGERS = {"/report", "/admin", "/retort"}


def _is_report_trigger(message: Message) -> bool:
    """Return True if this message is a report command in reply to another message."""
    if not message.reply_to_message:
        return False
    text = (message.text or "").strip()
    if not text:
        return False
    first_word = text.split()[0].lower()
    # Strip bot username suffix: /report@mybot → /report
    first_word = first_word.split("@")[0]
    if first_word in REPORT_TRIGGERS:
        return True
    if "@admin" in text.lower():
        return True
    return False


def _make_link(chat_id: int, message_id: int) -> str | None:
    """Build a deep link to a message. Only works for supergroups."""
    chat_id_str = str(abs(chat_id))
    if chat_id_str.startswith("100"):
        peer_id = abs(chat_id) - 1_000_000_000_000
        return f"https://t.me/c/{peer_id}/{message_id}"
    return None


def _mute_extend_keyboard(chat_id: int, user_id: int):
    """Buttons shown after the default 24h mute — let admin extend if needed."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📅 Тиждень",
            callback_data=f"report_mute_ext:week:{chat_id}:{user_id}",
        ),
        InlineKeyboardButton(
            text="🗓 Місяць",
            callback_data=f"report_mute_ext:month:{chat_id}:{user_id}",
        ),
        InlineKeyboardButton(
            text="♾ Назавжди",
            callback_data=f"report_mute_ext:forever:{chat_id}:{user_id}",
        ),
    )
    return builder.as_markup()


def _report_keyboard(chat_id: int, user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⛔️ Бан",
            callback_data=f"report_ban:{chat_id}:{user_id}",
        ),
        InlineKeyboardButton(
            text="🔇 Мут",
            callback_data=f"report_mute:{chat_id}:{user_id}",
        ),
        InlineKeyboardButton(
            text="✅ Ігнор",
            callback_data=f"report_ignore:{chat_id}:{user_id}",
        ),
    )
    return builder.as_markup()


async def _get_admins(bot: Bot, chat_id: int) -> set[int]:
    """Return cached set of non-bot admin IDs. Populate cache on first call."""
    if chat_id in fl.ADMINS_CACHE:
        return fl.ADMINS_CACHE[chat_id]
    admins = await bot.get_chat_administrators(chat_id)
    admin_ids = {a.user.id for a in admins if not a.user.is_bot}
    fl.ADMINS_CACHE[chat_id] = admin_ids
    return admin_ids


async def _register_admins(db: aiosqlite.Connection, admin_ids: set[int], chat_id: int):
    """Add all chat admins to report_mutes with status=1 if not already there."""
    for admin_id in admin_ids:
        await db.execute(
            """
            INSERT OR IGNORE INTO report_mutes (admin_id, chat_id, status)
            VALUES (?, ?, 1)
            """,
            (admin_id, chat_id),
        )
    await db.commit()


async def set_report_status(
    db: aiosqlite.Connection, admin_id: int, chat_id: int, status: int
):
    """Set report notification status for an admin in a chat (0=off, 1=on)."""
    await db.execute(
        "UPDATE report_mutes SET status = ? WHERE admin_id = ? AND chat_id = ?",
        (status, admin_id, chat_id),
    )
    await db.commit()


async def _get_active_recipients(db: aiosqlite.Connection, chat_id: int) -> list[int]:
    """Return admin_ids who have status=1 (want to receive reports) for this chat."""
    async with db.execute(
        "SELECT admin_id FROM report_mutes WHERE chat_id = ? AND status = 1",
        (chat_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def _get_user_name(bot: Bot, chat_id: int, user_id: int) -> str:
    """Return user's full name for public notices. Falls back to ID if unavailable."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.user.full_name
    except Exception:
        return str(user_id)


# ─── Report trigger handler ──────────────────────────────────────


@report_router.message(
    F.chat.type.in_({"group", "supergroup"}),
    _is_report_trigger,
)
async def report_handler(message: Message, bot: Bot, db: aiosqlite.Connection):
    reported_msg = message.reply_to_message
    reported_user = reported_msg.from_user

    # Delete the report command so it doesn't clutter the chat
    try:
        await message.delete()
    except Exception:
        pass

    if not reported_user or reported_user.is_bot:
        # Silently ignore reports on bots or anonymous messages
        return

    chat_id = message.chat.id

    # Get admins early — needed to ignore reports on admins
    try:
        admin_ids = await _get_admins(bot, chat_id)
    except Exception as e:
        logger.error(f"Cannot get admins for {chat_id}: {e}")
        return

    if reported_user.id in admin_ids:
        # Silently ignore reports on admins
        return

    chat_name = message.chat.title or str(chat_id)
    user_id = reported_user.id
    user_name = reported_user.full_name
    username = f"@{reported_user.username}" if reported_user.username else "немає"
    msg_id = reported_msg.message_id

    reported_text = reported_msg.text or reported_msg.caption or "[медіа без тексту]"
    if len(reported_text) > 200:
        reported_text = reported_text[:200] + "…"

    link = _make_link(chat_id, msg_id)
    link_line = f'\n🔗 <a href="{link}">Перейти до повідомлення</a>' if link else ""

    report_text = (
        f"🚨 <b>Репорт</b>\n"
        f"Чат: <b>{chat_name}</b>\n"
        f"Юзер: <b>{user_name}</b> ({username})\n"
        f"ID: <code>{user_id}</code>\n"
        f"Повідомлення: {reported_text}"
        f"{link_line}"
    )

    keyboard = _report_keyboard(chat_id, user_id)

    # Register admins in DB (INSERT OR IGNORE — existing records untouched)
    await _register_admins(db, admin_ids, chat_id)

    # Send only to those with status=1
    recipients = await _get_active_recipients(db, chat_id)

    sent_count = 0
    for admin_id in recipients:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=report_text,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            sent_count += 1
        except Exception:
            # Admin hasn't started the bot — skip silently
            pass

    if sent_count == 0:
        asyncio.create_task(
            send_timed_msg(
                bot,
                chat_id,
                "⚠️ Дякуємо за репорт! На жаль, жоден з адміністраторів ще не активував бота "
                "в особистих повідомленнях — сповіщення не надіслано. "
                "Попросіть адмінів написати /start цьому боту.",
                delay=45,
            )
        )
    else:
        asyncio.create_task(
            send_timed_msg(
                bot,
                chat_id,
                "✅ Скаргу надіслано адміністраторам.",
                delay=30,
            )
        )


# ─── Report action buttons ───────────────────────────────────────


@report_router.callback_query(
    F.data.startswith(("report_ban:", "report_mute:", "report_ignore:"))
)
async def report_action(callback: CallbackQuery, bot: Bot, db: aiosqlite.Connection):
    parts = callback.data.split(":")
    action = parts[0]
    chat_id = int(parts[1])
    user_id = int(parts[2])

    # Check admin rights via cache; fall back to API if cache is empty
    try:
        admin_ids = await _get_admins(bot, chat_id)
        if callback.from_user.id not in admin_ids:
            # Delete record entirely — same cleanup as members_status demotion path
            await db.execute(
                "DELETE FROM report_mutes WHERE admin_id = ? AND chat_id = ?",
                (callback.from_user.id, chat_id),
            )
            await db.commit()
            await callback.answer(
                "Тільки адміни чату можуть це зробити.", show_alert=True
            )
            return
    except Exception as e:
        logger.error(f"Cannot check admin status in {chat_id}: {e}")
        await callback.answer("Не вдалося перевірити права.", show_alert=True)
        return

    actor = callback.from_user.full_name

    if action == "report_ban":
        # Get name before banning — after ban get_chat_member may fail
        user_name = await _get_user_name(bot, chat_id, user_id)
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            logger.warning(
                f"REPORT BAN: user {user_id} ({user_name}) in chat {chat_id} "
                f"by admin {callback.from_user.id} ({actor})"
            )
            result_text = f"⛔️ Заблоковано. Дія: {actor}"
            asyncio.create_task(
                send_timed_msg(
                    bot, chat_id,
                    f"⛔️ Користувач {user_name} заблокований в чаті.",
                    delay=60,
                )
            )
        except Exception as e:
            logger.error(f"Report ban failed: {e}")
            result_text = "❌ Не вдалося заблокувати."

    elif action == "report_mute":
        user_name = await _get_user_name(bot, chat_id, user_id)
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(time.time()) + 86400,
            )
            logger.warning(
                f"REPORT MUTE 24h: user {user_id} ({user_name}) in chat {chat_id} "
                f"by admin {callback.from_user.id} ({actor})"
            )
            result_text = f"🔇 Замучено на 24г (дефолт). Дія: {actor}"
            asyncio.create_task(
                send_timed_msg(
                    bot, chat_id,
                    f"🔇 Користувач {user_name} обмежений у написанні на 24 години.",
                    delay=60,
                )
            )
            # Show extend buttons so admin can escalate without extra steps
            extend_keyboard = _mute_extend_keyboard(chat_id, user_id)
            try:
                await callback.message.edit_text(
                    callback.message.html_text + f"\n\n<b>{result_text}</b>\n"
                    "<i>Хочете продовжити мут?</i>",
                    reply_markup=extend_keyboard,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.warning(f"Cannot edit mute message: {e}")
            await callback.answer(result_text)
            return
        except Exception as e:
            logger.error(f"Report mute failed: {e}")
            result_text = "❌ Не вдалося замутити."

    else:  # report_ignore
        result_text = f"✅ Проігноровано. Дія: {actor}"

    try:
        await callback.message.edit_text(
            callback.message.html_text + f"\n\n<b>{result_text}</b>",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Cannot edit report message: {e}")

    await callback.answer(result_text)


# ─── Mute extend buttons ─────────────────────────────────────────


@report_router.callback_query(F.data.startswith("report_mute_ext:"))
async def report_mute_extend(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    duration = parts[1]  # week / month / forever
    chat_id = int(parts[2])
    user_id = int(parts[3])

    # Verify the person clicking is still an admin
    try:
        admin_ids = await _get_admins(bot, chat_id)
        if callback.from_user.id not in admin_ids:
            await callback.answer(
                "Тільки адміни чату можуть це зробити.", show_alert=True
            )
            return
    except Exception as e:
        logger.error(f"Cannot check admin status in {chat_id}: {e}")
        await callback.answer("Не вдалося перевірити права.", show_alert=True)
        return

    actor = callback.from_user.full_name

    duration_map = {
        # label for admin DM, public notice text, seconds (0 = permanent)
        "week":    ("тиждень",  "7 днів",       7 * 86400),
        "month":   ("місяць",   "30 днів",      30 * 86400),
        "forever": ("назавжди", "безстроково",  0),
    }
    label, public_label, seconds = duration_map[duration]

    user_name = await _get_user_name(bot, chat_id, user_id)

    try:
        kwargs = dict(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        if seconds:
            kwargs["until_date"] = int(time.time()) + seconds
        await bot.restrict_chat_member(**kwargs)
        logger.warning(
            f"REPORT MUTE EXT ({label}): user {user_id} ({user_name}) in chat {chat_id} "
            f"by admin {callback.from_user.id} ({actor})"
        )
        result_text = f"🔇 Мут продовжено на {label}. Дія: {actor}"
        asyncio.create_task(
            send_timed_msg(
                bot, chat_id,
                f"🔇 Користувач {user_name} обмежений у написанні {public_label}.",
                delay=60,
            )
        )
    except Exception as e:
        logger.error(f"Report mute extend failed: {e}")
        result_text = "❌ Не вдалося продовжити мут."

    try:
        # html_text keeps original formatting; split removes the "extend?" hint line
        base = callback.message.html_text.split("\n<i>")[0]
        await callback.message.edit_text(
            base + f"\n\n<b>{result_text}</b>",
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"Cannot edit mute extend message: {e}")

    await callback.answer(result_text)


# ─── /reports toggle ─────────────────────────────────────────────


async def _reports_keyboard(db: aiosqlite.Connection, bot: Bot, user_id: int):
    """Build keyboard from chats where this user is already registered in report_mutes."""
    async with db.execute(
        "SELECT chat_id, status FROM report_mutes WHERE admin_id = ?",
        (user_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return None

    builder = InlineKeyboardBuilder()
    for chat_id, status in rows:
        icon = "🔔" if status == 1 else "🔕"
        try:
            chat = await bot.get_chat(chat_id)
            name = chat.title or str(chat_id)
        except Exception:
            name = str(chat_id)
        builder.button(
            text=f"{icon} {name}",
            callback_data=f"toggle_reports:{chat_id}",
        )
    builder.adjust(1)
    return builder.as_markup()


@report_router.message(Command("reports"), F.chat.type == "private")
async def toggle_reports_cmd(message: Message, bot: Bot, db: aiosqlite.Connection):
    user_id = message.from_user.id
    keyboard = await _reports_keyboard(db, bot, user_id)

    intro = (
        "📣 <b>Репорти від учасників</b>\n\n"
        "Коли хтось у чаті надсилає <code>/report</code> у відповідь на підозріле повідомлення — "
        "бот пересилає його вам в особисті з кнопками <b>Бан / Мут / Ігнорувати</b>.\n\n"
        "Нижче — чати де ви зареєстровані як адмін.\n"
        "🔔 = отримуєте репорти   🔕 = вимкнено"
    )

    if not keyboard:
        await message.answer(
            intro + "\n\n"
            "⚙️ Поки що список порожній — репортів ще не надходило.\n"
            "Після першого репорту в будь-якому з ваших чатів список з'явиться тут автоматично."
        )
        return

    await message.answer(intro, reply_markup=keyboard)


@report_router.callback_query(F.data.startswith("toggle_reports:"))
async def toggle_reports_callback(
    callback: CallbackQuery, bot: Bot, db: aiosqlite.Connection
):
    chat_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    # Check that user is still an admin in this chat
    try:
        admin_ids = await _get_admins(bot, chat_id)
        if user_id not in admin_ids:
            # Delete stale record and refresh keyboard so the button disappears
            await db.execute(
                "DELETE FROM report_mutes WHERE admin_id = ? AND chat_id = ?",
                (user_id, chat_id),
            )
            await db.commit()
            keyboard = await _reports_keyboard(db, bot, user_id)
            try:
                await callback.message.edit_reply_markup(reply_markup=keyboard)
            except Exception:
                pass
            await callback.answer("Ви більше не адмін цього чату.", show_alert=True)
            return
    except Exception as e:
        logger.error(f"Cannot check admin status in {chat_id}: {e}")
        await callback.answer("Не вдалося перевірити права.", show_alert=True)
        return

    # Read current status
    async with db.execute(
        "SELECT status FROM report_mutes WHERE admin_id = ? AND chat_id = ?",
        (user_id, chat_id),
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        await callback.answer("Запис не знайдено.", show_alert=True)
        return

    new_status = 0 if row[0] == 1 else 1
    await set_report_status(db, user_id, chat_id, new_status)

    status_label = "ON" if new_status == 1 else "OFF"
    admin_name = callback.from_user.full_name
    logger.info(
        f"REPORT NOTIFY {status_label}: admin {user_id} ({admin_name}) in chat {chat_id}"
    )

    keyboard = await _reports_keyboard(db, bot, user_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass

    status_text = "увімкнено 🔔" if new_status == 1 else "вимкнено 🔕"
    await callback.answer(f"Репорти для цього чату {status_text}")
