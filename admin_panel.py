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
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest


async def on_admin(db, chat_id, admin_id):
    await db.execute(
        """
        INSERT INTO admins (chat_id, admin_id, status) 
        VALUES (?, ?, 1)
        ON CONFLICT(chat_id, admin_id) DO UPDATE SET status = 1
        """,
        (chat_id, admin_id),
    )
    await db.commit()


async def off_admin(db, chat_id, admin_id):
    await db.execute(
        """
        INSERT INTO admins (chat_id, admin_id, status) 
        VALUES (?, ?, 0)
        ON CONFLICT(chat_id, admin_id) DO UPDATE SET status = 0
        """,
        (chat_id, admin_id),
    )
    await db.commit()


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


async def check_admin_groups(db, user_id):
    c = await db.cursor()
    await c.execute(
        "SELECT chat_id FROM admins WHERE admin_id = ? AND status = 1",
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
                    text=name.title, callback_data=f"ignore:{id}", style="primary"
                ),
                InlineKeyboardButton(
                    text="ON", callback_data=f"on:{id}:{feature}", style="success"
                ),
            )
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Видаляемо з бази
            c = await db.cursor()
            await c.execute(
                "DELETE FROM chat_links WHERE chat_id = ?",
                (id,),
            )
            await db.commit()
            continue
        except Exception as e:
            print(f"Щось інше {e}")
            continue
    builder.add(
        InlineKeyboardButton(text="Назад", callback_data="my_settings"),
    )
    builder.adjust(3)
    return builder.as_markup()  # Повертаємо готовий результат


async def add_admin(db, bot, chat_ids):
    builder = InlineKeyboardBuilder()
    for id in chat_ids:
        try:
            name = await bot.get_chat(id)
            builder.add(
                InlineKeyboardButton(
                    text=name.title, callback_data=f"name_group:{id}", style="primary"
                ),
            )
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Видаляемо з бази
            c = await db.cursor()
            await c.execute(
                "DELETE FROM chat_links WHERE chat_id = ?",
                (id,),
            )
            await db.commit()
            continue
        except Exception as e:
            print(f"Щось інше {e}")
            continue
    builder.add(
        InlineKeyboardButton(text="Назад", callback_data="my_settings"),
    )
    builder.adjust(1)
    return builder.as_markup()  # Повертаємо готовий результат


async def admin_list(db, bot, chat_id):
    builder = InlineKeyboardBuilder()
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin_id in admins:
            # Пропускаємо ботів, щоб не пробувати призначити їх адмінами
            if admin_id.user.is_bot:
                continue

            builder.add(
                InlineKeyboardButton(
                    text="Вилучити",
                    callback_data=f"remove_moder:{chat_id}:{admin_id.user.id}",
                    style="danger",
                ),
                InlineKeyboardButton(
                    text=admin_id.user.full_name,
                    callback_data="adm_name",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Призначити",
                    callback_data=f"add_moder:{chat_id}:{admin_id.user.id}",
                    style="success",
                ),
            )
    except Exception as e:
        # якщо бот не адмін або його видалили  чистимо базу
        await db.execute("DELETE FROM chat_links WHERE chat_id = ?", (chat_id,))
        await db.commit()

    builder.add(
        InlineKeyboardButton(text="Назад", callback_data="my_settings"),
    )
    builder.adjust(3)
    return builder.as_markup()


##############

admin_router = Router()

# Одне правило для всього файлу: пропускати ТІЛЬКИ приватні повідомлення
admin_router.message.filter(F.chat.type == "private")


#####
@admin_router.message(
    Command(
        "my_settings",
        "start",
        "add_admin",
    )
)
async def admin_start(message: Message, db):

    if message.text == "/my_settings":
        text_settint = (
            "⚙️ Параметри захисту\n\n"
            "За замовчуванням увімкнено найбільш збалансований режим модерації. "
            "Використовуйте меню нижче для ручного коригування модулів, якщо цього вимагають правила вашого чату."
        )
        await message.answer(text_settint, reply_markup=settings())
    elif message.text == "/add_admin":
        admin_help_text = (
            "👮‍♂️ <b>Список груп, де ви є власником:</b>\n\n"
            "Оберіть чат, куди хочете додати адмінів, які зможуть керувати налаштуваннями бота."
            # "Контрорлюйте кому ви надали право керувати своїми чатами за допомогою команди /my_admins"
        )
        chat_ids = await check_own_groups(db, message.from_user.id)
        await message.answer(
            admin_help_text, reply_markup=await add_admin(db, message.bot, chat_ids)
        )

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
            "name_group:",
            "add_moder",
            "remove_moder:",
        )
    )
)
async def admin_settings(callback: CallbackQuery, db: aiosqlite.Connection):

    result = callback.data
    if result.startswith("on:"):
        chat_id = int(result.split(":")[1])
        result = result.split(":")[2]
        member = await callback.bot.get_chat_member(chat_id, callback.from_user.id)
        if member.status in ["administrator", "creator"] or callback.from_user.id == config.root:
            await edit_setting(db, chat_id, result, 1)
            await callback.message.edit_text(
                f"status ввімкнено для чату {chat_id}", reply_markup=settings()
            )
        else:
            await callback.answer("Cхоже в вас на це нема права", show_alert=True)
        fl.get_chat_settings.cache_invalidate(db, chat_id)
    elif result.startswith("off:"):
        chat_id = int(result.split(":")[1])
        result = result.split(":")[2]
        member = await callback.bot.get_chat_member(chat_id, callback.from_user.id)
        if member.status in ["administrator", "creator"] or callback.from_user.id == config.root:
            await edit_setting(db, chat_id, result, 0)
            await callback.message.edit_text(
                f"status вимкнено для чату {chat_id}", reply_markup=settings()
            )
        else:
            await callback.answer("Cхоже в вас на це нема права", show_alert=True)
        fl.get_chat_settings.cache_invalidate(db, chat_id)
    elif result == "my_settings":
        text_settint = (
            "⚙️ Параметри захисту\n\n"
            "Використовуйте меню нижче для ручного коригування модулів, якщо цього вимагають правила вашого чату."
        )
        await callback.message.edit_text(text_settint, reply_markup=settings())
    elif result.startswith("name_group:"):  
            chat_id = int(result.split(":")[1])

            # # БРОНЯ
            # own_ids = await check_own_groups(db, callback.from_user.id)
            
            # if chat_id in own_ids:
            text = "⚙️ Список адміністраторів чату\n"
            await callback.message.edit_text(
                text, reply_markup=await admin_list(db, callback.bot, chat_id)
            )
            # else:
            #     await callback.answer("❌ Керувати модераторами може виключно власник чату!", show_alert=True)
    elif result.startswith("remove_moder:"):
        chat_id = int(result.split(":")[1])
        admin_id = result.split(":")[2]
        await off_admin(db, chat_id, admin_id)
        await callback.answer("✅ Адміна вилучено", show_alert=True)
    elif result.startswith("add_moder:"):
        chat_id = int(result.split(":")[1])
        admin_id = result.split(":")[2]
        await on_admin(db, chat_id, admin_id)
        await callback.answer("✅ Адміна додано", show_alert=True)

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
        own_ids = await check_own_groups(db, callback.from_user.id)
        admin_ids = await check_admin_groups(db, callback.from_user.id)
        all_chats = list(set(own_ids + admin_ids))
        if all_chats:
            await callback.message.edit_text(
                text,
                reply_markup=await on_off_buttons(db, callback.bot, all_chats, result),
            )

        elif not own_ids and not admin_ids:
            await callback.message.edit_text(
                "⚠️ <b>Налаштування доступні лише власнику чату та призначеним адмінам!</b>\n\n"
                "У моїй базі не знайдено груп, якими ви можете керувати.\n"
                "👉 Додайте мене у свій чат або попросіть власника надати вам права, а потім спробуйте знову:\n/my_settings",
                parse_mode="HTML",
            )
