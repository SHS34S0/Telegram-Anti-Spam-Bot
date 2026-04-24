import pytest
from unittest.mock import AsyncMock, MagicMock
from filters import get_channel_owner


@pytest.mark.asyncio
async def test_get_channel_owner_returns_creator_id():
    mock_bot = MagicMock()
    # bot.get_chat_administrat має повернути список словників ід та статус
    mock_bot.get_chat_administrators = AsyncMock(
        return_value=[
            MagicMock(status="member", user=MagicMock(id=101)),
            MagicMock(status="creator", user=MagicMock(id=102)),
            MagicMock(status="member", user=MagicMock(id=103)),
            MagicMock(status="member", user=MagicMock(id=104)),
        ]
    )
    result = await get_channel_owner(mock_bot, channel_id=4354568)
    assert result == 102

    mock_bot.get_chat_administrators.assert_called_once_with(chat_id=4354568)


@pytest.mark.asyncio
async def test_get_channel_owner_returns_none_when_no_creator():
    mock_bot = MagicMock()
    mock_bot.get_chat_administrators = AsyncMock(
        return_value=[
            MagicMock(status="member", user=MagicMock(id=101)),
            MagicMock(status="member", user=MagicMock(id=102)),
        ]
    )
    result = await get_channel_owner(mock_bot, channel_id=4354568)
    assert result == None

    mock_bot.get_chat_administrators.assert_called_once_with(chat_id=4354568)


@pytest.mark.asyncio
async def test_get_channel_owner_returns_none_on_api_error():
    mock_bot = MagicMock()
    mock_bot.get_chat_administrators.side_effect = Exception("немає прав")
    result = await get_channel_owner(mock_bot, channel_id=4354568)
    assert result == None

    mock_bot.get_chat_administrators.assert_called_once_with(chat_id=4354568)
