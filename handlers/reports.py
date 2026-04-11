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


def _report_keyboard(chat_id: int, user_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="⛔️ Бан",
            callback_data=f"report_ban:{chat_id}:{user_id}",
        ),
        InlineKeyboardButton(
            text="🔇 Мут 24г",
            callback_data=f"report_mute:{chat_id}:{user_id}",
        ),
        InlineKeyboardButton(
            text="✅ Ігнорувати",
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


async def _get_active_recipients(db: aiosqlite.Connection, chat_id: int) -> list[int]:
    """Return admin_ids who have status=1 (want to receive reports) for this chat."""
    c = await db.cursor()
    await c.execute(
        "SELECT admin_id FROM report_mutes WHERE chat_id = ? AND status = 1",
        (chat_id,),
    )
    rows = await c.fetchall()
    return [row[0] for row in rows]


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

    # Get admins from cache (API call only on first report for this chat)
    try:
        admin_ids = await _get_admins(bot, chat_id)
    except Exception as e:
        logger.error(f"Cannot get admins for {chat_id}: {e}")
        return

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
        from utils import send_timed_msg

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


# ─── Report action buttons ───────────────────────────────────────


@report_router.callback_query(
    F.data.startswith(("report_ban:", "report_mute:", "report_ignore:"))
)
async def report_action(callback: CallbackQuery, bot: Bot):
    parts = callback.data.split(":")
    action = parts[0]
    chat_id = int(parts[1])
    user_id = int(parts[2])

    # Check admin rights via cache; fall back to API if cache is empty
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

    if action == "report_ban":
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            logger.warning(
                f"REPORT BAN: user {user_id} in {chat_id} by {callback.from_user.id}"
            )
            result_text = f"⛔️ Заблоковано. Дія: {actor}"
        except Exception as e:
            logger.error(f"Report ban failed: {e}")
            result_text = "❌ Не вдалося заблокувати."

    elif action == "report_mute":
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(time.time()) + 86400,
            )
            logger.warning(
                f"REPORT MUTE: user {user_id} in {chat_id} by {callback.from_user.id}"
            )
            result_text = f"🔇 Замучено на 24г. Дія: {actor}"
        except Exception as e:
            logger.error(f"Report mute failed: {e}")
            result_text = "❌ Не вдалося замутити."

    else:  # report_ignore
        result_text = f"✅ Проігноровано. Дія: {actor}"

    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n<b>{result_text}</b>",
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await callback.answer(result_text)


# ─── /reports toggle ─────────────────────────────────────────────


async def _reports_keyboard(db: aiosqlite.Connection, bot: Bot, user_id: int):
    """Build keyboard from chats where this user is already registered in report_mutes."""
    c = await db.cursor()
    await c.execute(
        "SELECT chat_id, status FROM report_mutes WHERE admin_id = ?",
        (user_id,),
    )
    rows = await c.fetchall()

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

    # Read current status
    c = await db.cursor()
    await c.execute(
        "SELECT status FROM report_mutes WHERE admin_id = ? AND chat_id = ?",
        (user_id, chat_id),
    )
    row = await c.fetchone()

    if not row:
        await callback.answer("Запис не знайдено.", show_alert=True)
        return

    new_status = 0 if row[0] == 1 else 1
    await db.execute(
        "UPDATE report_mutes SET status = ? WHERE admin_id = ? AND chat_id = ?",
        (new_status, user_id, chat_id),
    )
    await db.commit()

    keyboard = await _reports_keyboard(db, bot, user_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass

    status_text = "увімкнено 🔔" if new_status == 1 else "вимкнено 🔕"
    await callback.answer(f"Репорти для цього чату {status_text}")
