from aiogram import Router, F
from aiogram import Bot, Dispatcher, html, F
from aiogram.filters import Command
from aiogram.types import Message
import aiosqlite
import filters as fl

from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
import config


async def check_own_groups(db, user_id):
    c = await db.cursor()
    await c.execute(
        "SELECT chat_id FROM chat_links WHERE owner_id = ?",
        (user_id,),
    )
    rows = await c.fetchall()  # отримуємо список кортежів
    chat_ids = [
        row[0] for row in rows
    ]  # беремо перший (і єдиний) елемент кожного кортежу
    print(f"вивід з бази у вигляді списку: {chat_ids}")
    return chat_ids


async def edit_setting(db, chat_id, feature, status):
    await db.execute(
        f"UPDATE chat_links SET {feature} = ? WHERE chat_id = ?",
        (status, chat_id),
    )
    await db.commit()


def settings():
    builder = InlineKeyboardBuilder()

    builder.add(
        InlineKeyboardButton(
            text="🔗 Заборона посилань", callback_data="stop_links", style="primary"
        ),
        InlineKeyboardButton(
            text="📢 Писати від імені каналу",
            callback_data="stop_channel",
            style="primary",
        ),
        InlineKeyboardButton(
            text="💳 Фільтр карток", callback_data="card_number", style="primary"
        ),
        InlineKeyboardButton(
            text="🔥 Спам реакціями", callback_data="reaction_spam", style="primary"
        ),
        InlineKeyboardButton(
            text="🚫 рос. мова", callback_data="rus_language", style="primary"
        ),
        InlineKeyboardButton(
            text="🎭 Фільтр емодзі", callback_data="emoji_checker", style="primary"
        ),
    )
    builder.adjust(1)
    return builder.as_markup()  # Повертаємо готовий результат


async def on_off_buttons(db, bot, chat_ids, feature):
    builder = InlineKeyboardBuilder()
    for id in chat_ids:
        try:
            name = await bot.get_chat(id)
            builder.add(
                InlineKeyboardButton(
                    text="OFF", callback_data=f"off:{id}:{feature}", style="danger"
                ),
                InlineKeyboardButton(
                    text=name.title, callback_data="name", style="primary"
                ),
                InlineKeyboardButton(
                    text="ON", callback_data=f"on:{id}:{feature}", style="success"
                ),
            )
        except Exception as e:
            # Видаляемо з бази
            c = await db.cursor()
            await c.execute(
                "DELETE FROM chat_links WHERE chat_id = ?",
                (id,),
            )
            await db.commit()
            continue
    builder.add(
        InlineKeyboardButton(text="Назад", callback_data="my_settings"),
    )
    builder.adjust(3)
    return builder.as_markup()  # Повертаємо готовий результат


##############

admin_router = Router()

# Одне правило для всього файлу: пропускати ТІЛЬКИ приватні повідомлення
admin_router.message.filter(F.chat.type == "private")


#####
@admin_router.message(Command("my_settings", "start"))
async def admin_start(message: Message, db):

    if message.text == "/my_settings":
        text_settint = (
            "⚙️ Параметри захисту\n\n"
            "За замовчуванням увімкнено найбільш збалансований режим модерації. "
            "Використовуйте меню нижче для ручного коригування модулів, якщо цього вимагають правила вашого чату."
        )
        await message.answer(text_settint, reply_markup=settings())

    else:
        text = (
            f"👋 <b>Вітаю, {html.bold(message.from_user.full_name)}!</b>\n"
            + config.TEXT
        )
        await message.answer(text)


@admin_router.callback_query(
    F.data.startswith(
        (
            "on:",
            "off:",
            "stop_channel",
            "stop_links",
            "card_number",
            "rus_language",
            "stop_word",
            "emoji_checker",
            "reaction_spam",
            "my_settings",
        )
    )
)
async def admin_settings(callback: CallbackQuery, db: aiosqlite.Connection):

    result = callback.data
    if result.startswith("on:"):
        chat_id = int(result.split(":")[1])
        result = result.split(":")[2]
        await edit_setting(db, chat_id, result, 1)
        await callback.message.edit_text(
            f"status ON для чату {chat_id}", reply_markup=settings()
        )
        fl.get_chat_settings.cache_invalidate(db, chat_id)
    elif result.startswith("off:"):
        chat_id = int(result.split(":")[1])
        result = result.split(":")[2]
        await edit_setting(db, chat_id, result, 0)
        await callback.message.edit_text(
            f"status OFF для чату {chat_id}", reply_markup=settings()
        )
        fl.get_chat_settings.cache_invalidate(db, chat_id)
    elif result == "my_settings":
        text_settint = (
            "⚙️ Параметри захисту\n\n"
            "Використовуйте меню нижче для ручного коригування модулів, якщо цього вимагають правила вашого чату."
        )
        await callback.message.edit_text(text_settint, reply_markup=settings())

    elif result in [
        "stop_channel",
        "stop_links",
        "card_number",
        "rus_language",
        "stop_word",
        "emoji_checker",
        "reaction_spam",
    ]:
        text = config.description_buttons(result)
        chat_ids = await check_own_groups(db, callback.from_user.id)
        if chat_ids:
            await callback.message.edit_text(
                text,
                reply_markup=await on_off_buttons(db, callback.bot, chat_ids, result),
            )
        else:
            await callback.message.edit_text(
                "⚠️ <b>Налаштування доступні виключно власнику чату!</b>\n\n"
                "У моїй базі не знайдено груп, якими ви володієте. \n"
                "Спочатку додайте мене у свій чат, а потім відкрийте це меню знову.\n/my_settings",
                parse_mode="HTML",
            )