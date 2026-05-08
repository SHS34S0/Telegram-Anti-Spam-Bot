import pytest
from unittest.mock import AsyncMock, patch

from utils import safe_ban


@pytest.fixture
def mock_message():
    mock_msg = AsyncMock()
    return mock_msg


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_ban(mock_send_remote_log, mock_message):
    await safe_ban(mock_message, 124345357455)
    mock_message.chat.ban.assert_called_once()
    mock_send_remote_log.assert_called_once()


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_ban_timed(mock_send_remote_log, mock_message):
    await safe_ban(mock_message, 124345357455, 60)
    mock_message.chat.ban.assert_called_once()
    mock_send_remote_log.assert_called_once()


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_ban_error(mock_send_remote_log, mock_message):
    mock_message.chat.ban.side_effect = Exception("Помилка", "log")
    await safe_ban(mock_message, 124345357455)
    mock_message.chat.ban.assert_called_once()
    mock_send_remote_log.assert_called_once()
