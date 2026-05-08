import pytest
from unittest.mock import AsyncMock, patch

from utils import safe_mute


@pytest.fixture
def mock_message():
    mock_msg = AsyncMock()
    return mock_msg


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_mute(mock_send_remote_log, mock_message):
    await safe_mute(mock_message, 124345357455)
    mock_message.bot.restrict_chat_member.assert_called_once()
    mock_send_remote_log.assert_called_once()


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_mute_error(mock_send_remote_log, mock_message):
    mock_message.bot.restrict_chat_member.side_effect = Exception("Помилка", "log")
    await safe_mute(mock_message, 124345357455)
    mock_message.bot.restrict_chat_member.assert_called_once()
    mock_send_remote_log.assert_called_once()
