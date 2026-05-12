import asyncio
import time

from aiogram import Router, Bot
import logging
from aiogram.types import MessageReactionUpdated
import config
import filters as fl
import messages as msg
from utils import send_timed_msg, delete_user_history

message_reaction = Router()
logger = logging.getLogger(__name__)


@message_reaction.message_reaction()
async def reaction_handler(reaction: MessageReactionUpdated, bot: Bot):
    user = reaction.user
    if not user:
        return  # це може бути анонімний адмін або канал

    u_id = user.id
    c_id = reaction.chat.id
    user_full_name = reaction.user.full_name
    #  Щоб мати можливість видаляти повідомлення вручну де я не є модератором
    if str(u_id) == str(config.root):
        for react in reaction.new_reaction:
            if getattr(react, "emoji", None) in ("🤡", "👎", "💩"):
                try:
                    await bot.delete_message(
                        chat_id=c_id, message_id=reaction.message_id
                    )
                except Exception as e:
                    logger.error(
                        f"Помилка {e} при спробі видалити повідомлення через реакцію 🤡 від користувача {user_full_name} ({u_id})\nГрупа {reaction.chat.title} ({c_id})"
                    )
                return
    # example: {123456: {-100987: {99: (1715000000, [ReactionTypeEmoji(emoji='👍'), ReactionTypeEmoji(emoji='❤️')])}}}
    now = time.time()
    if reaction.new_reaction:
        if u_id not in fl.REACTION_HISTORY:
            fl.REACTION_HISTORY[u_id] = {}
        if c_id not in fl.REACTION_HISTORY[u_id]:
            fl.REACTION_HISTORY[u_id][c_id] = {}
        fl.REACTION_HISTORY[u_id][c_id][reaction.message_id] = (
            now,
            reaction.new_reaction,
        )
    else:
        if u_id in fl.REACTION_HISTORY:
            if c_id in fl.REACTION_HISTORY[u_id]:
                fl.REACTION_HISTORY[u_id][c_id].pop(reaction.message_id, None)
    # ==========================================================
    if await fl.msg_count(u_id, c_id):
        return
    # Ставить реакції. чи забирає ?
    if not reaction.new_reaction:
        return
    dc_number = await fl.check_dc_number(bot, u_id)
    if dc_number == 100 or u_id in fl.GLOBAL_BANNED:
        await bot.ban_chat_member(chat_id=c_id, user_id=u_id)
        await delete_user_history(bot, u_id)
        logger.warning(
            f"Заблоковано {user_full_name} {u_id}\nГрупа {reaction.chat.title} {c_id} \nПричина: Reaction Spam"
        )

        asyncio.create_task(
            send_timed_msg(bot, c_id, msg.SpamMessage.reaction_spam(user_full_name))
        )
        return
