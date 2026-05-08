import pytest
from unittest.mock import AsyncMock, patch

from utils import send_timed_msg


@patch("utils.asyncio.sleep")
@patch("utils.safe_delete")
@pytest.mark.asyncio
async def test_send_timed_msg(safe_delete, mock_sleep):
    bot = AsyncMock()
    await send_timed_msg(bot, 968767657, "text")
    safe_delete.assert_called_once()
    mock_sleep.assert_called_once()
    bot.send_message.assert_called_once()
