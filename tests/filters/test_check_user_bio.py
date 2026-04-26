import pytest
from unittest.mock import AsyncMock, MagicMock
from filters import check_user_bio


@pytest.mark.asyncio
async def test_check_user_bio_no_bio():
    mock_bot = MagicMock()
    # AsyncMock замість звичайного MagicMock коли метод викликається через await
    mock_bot.get_chat = AsyncMock(return_value=MagicMock(bio=None))
    # викликаєш реальну функцію, але замість справжнього Telegram-бота передаєш свій мок
    result = await check_user_bio(mock_bot, user_id=123)
    assert result == False
    # не мок бота а саме get_chat бо саме його ми викликали
    mock_bot.get_chat.assert_called_once_with(123)


@pytest.mark.asyncio
async def test_check_user_bio_invite_link():
    mock_bot = MagicMock()
    mock_bot.get_chat = AsyncMock(
        return_value=MagicMock(bio="мій канал https://t.me/+PlMp5xVP6r1lNjA0 ✨")
    )
    result = await check_user_bio(mock_bot, user_id=123)
    assert result == True
    mock_bot.get_chat.assert_called_once_with(123)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bio, expected",
    [
        ("Лучший прогноз смотри в сторисе", 100),
        ("💙 Переходь у мій секретний блог з відвертими фото - @...", 100),
    ],
)
async def test_check_user_bio_stop_words(bio, expected):
    mock_bot = MagicMock()
    mock_bot.get_chat = AsyncMock(return_value=MagicMock(bio=bio))
    result = await check_user_bio(mock_bot, user_id=123)
    assert result == expected


@pytest.mark.asyncio
async def test_check_user_bio_clean():
    mock_bot = MagicMock()
    mock_bot.get_chat = AsyncMock(return_value=MagicMock(bio=""))
    result = await check_user_bio(mock_bot, user_id=123)
    assert result == False
    mock_bot.get_chat.assert_called_once_with(123)
