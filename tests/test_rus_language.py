import pytest
from filters import rus_language


def test_rus_language():
    assert rus_language("То були мы разом") == True
    assert rus_language("этот или тот") == True
    assert rus_language("ъ") == True
    assert rus_language("моё или твоё") == True
    assert rus_language("потому что") == True
    assert rus_language("как то так") == True
    assert rus_language("да или нет") == True
    assert rus_language("почему") == True
    assert rus_language("вот как то так") == True
    assert rus_language("только сегодня") == True
    assert rus_language("только здесь") == True
    assert rus_language("только сейчас") == True
    assert rus_language("я теперь счастлив") == True
    assert rus_language("ти никогда не пил кофе") == True
    assert rus_language("Я очень люблю кофе") == True
    assert rus_language("когда я пью кофе") == True
    assert rus_language("мі там где хорошо") == True
    assert rus_language("да нет") == True
    assert rus_language("я конечно тут") == True
    assert rus_language("наверное") == True
    assert rus_language("дайте пожалуйста") == True
    assert rus_language("скажу вам спасибо") == True
    assert rus_language("я человек") == True
    assert rus_language("жизнь") == True
    assert rus_language("такой") == True
    assert rus_language("могу") == True
    assert rus_language("понимаю") == True
    assert rus_language("должен") == True
    assert rus_language("нужен") == True
    assert rus_language("говоря") == True
    assert rus_language("личку") == True
    assert rus_language("работа") == True
    assert rus_language("нужен") == True
    assert rus_language("каждую") == True

    assert rus_language("Паляниця") == None
    assert rus_language("Укрзалізниця") == None
    assert rus_language("привіт") == None
    assert (
        rus_language(
            "Привіт усім! Підкажіть, будь ласка, як краще налаштувати aiogram для роботи з базою даних? Буду вдячний за допомогу."
        )
        == None
    )

    assert rus_language("🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥") == None
