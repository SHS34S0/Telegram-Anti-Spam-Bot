import pytest
from filters import emoji_checker


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟🌟",
            0,
        ),
        (
            "Привіт усім! Підкажіть, будь ласка, як краще налаштувати aiogram для роботи з базою даних? Буду вдячний за допомогу.",
            100,
        ),
    ],
)
def test_emoji_checker_exact(text, expected):
    assert emoji_checker(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "🌟🌟🌟🌟🌟🌟🌟🌟 Высокий доход ежедневно ! от📝📝📝💵—📝📝📝📝💵💰 Никаких вложений ! Берем с любого возраста! Гибкий график! Обучим всему с нуля! Одно из лучших предложений на сегодня! По всем вопроса✍️в ЛС",
    ],
)
def test_emoji_checker_is_spam(text):
    assert emoji_checker(text) > 70


@pytest.mark.parametrize(
    "text",
    [
        "🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🧡🔥🔥🔥🔥🔥🔥🔥❗️🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥❗️🅰️🅰️🅰️🅰️ ✈️🅰️🅰️🅰️🅰️ ✈️😌😚😌😚 ✈️⬇️⬇️⬇️⬇️⬇️",
    ],
)
def test_emoji_checker_is_not_spam(text):
    assert emoji_checker(text) < 5
