import pytest
from filters import has_weird_chars


def test_has_weird_chars():
    assert has_weird_chars("Пᴏкажу персик") == True
    assert has_weird_chars("Мᴀма") == True
    assert has_weird_chars("ʜорм") == True
    assert has_weird_chars("Маᴋбук") == True
    assert has_weird_chars("Піʙдень") == True
    assert has_weird_chars("ᴍало") == True
    assert has_weird_chars("піʙдᴇнь") == True
    assert has_weird_chars("вітеᴘ") == True


def test_has_no_weird_chars():
    assert has_weird_chars("Покажу персик") == False
    assert has_weird_chars("Мама") == False
    assert has_weird_chars("норм") == False
    assert has_weird_chars("Макбук") == False
    assert has_weird_chars("Південь") == False
    assert has_weird_chars("мало") == False
    assert has_weird_chars("південь") == False
    assert has_weird_chars("вітер") == False
