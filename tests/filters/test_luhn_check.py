import pytest
from filters import luhn_check


@pytest.mark.parametrize(
    "card_number, expected",
    [
        ("5488550041993308", True),
        ("111122223333444", False),
    ],
)
def test_luhn_check(card_number, expected):
    assert luhn_check(card_number) == expected
