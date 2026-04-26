import pytest
from filters import has_weird_chars


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Пᴏкажу персик", True),
        ("Мᴀма", True),
        ("ʜорм", True),
        ("Маᴋбук", True),
        ("Піʙдень", True),
        ("ᴍало", True),
        ("піʙдᴇнь", True),
        ("вітеᴘ", True),
        ("Покажу персик", False),
        ("Мама", False),
        ("норм", False),
        ("Макбук", False),
        ("Південь", False),
        ("мало", False),
        ("південь", False),
        ("вітер", False),
    ],
)
def test_has_weird_chars(text, expected):
    assert has_weird_chars(text) == expected
