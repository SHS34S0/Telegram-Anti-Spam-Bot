import pytest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from utils import safe_delete


@pytest.fixture
def mock_msg():
    mock_msg = AsyncMock()
    mock_msg.from_user.is_bot = False
    return mock_msg


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
# функція містить залежність з fl. тож її треба предати як аргумент
async def test_safe_delete_success(mock_send_remote_log, mock_msg):
    await safe_delete(mock_msg)
    mock_msg.delete.assert_called_once()
    mock_send_remote_log.assert_called_once()


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_delete_already_deleted(mock_send_remote_log, mock_msg):
    mock_msg.delete.side_effect = TelegramBadRequest(
        "deleteMessage", "message to delete not found"
    )
    await safe_delete(mock_msg)
    mock_msg.delete.assert_called_once()
    mock_send_remote_log.assert_not_called()


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_delete_unexpected_error(mock_send_remote_log, mock_msg):
    mock_msg.delete.side_effect = Exception("щось пішло не так")
    await safe_delete(mock_msg)
    mock_msg.delete.assert_called_once()
    mock_send_remote_log.assert_called_once()


@patch("utils.fl.send_remote_log")
@pytest.mark.asyncio
async def test_safe_delete_is_bot(mock_send_remote_log, mock_msg):
    mock_msg.from_user.is_bot = True
    await safe_delete(mock_msg)
    mock_msg.delete.assert_called_once()
    mock_send_remote_log.assert_not_called()
