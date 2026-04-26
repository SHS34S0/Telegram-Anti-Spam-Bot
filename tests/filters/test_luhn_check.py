import pytest
from filters import luhn_check

def test_luna_check():
    assert luhn_check("5488550041993308") == True
    assert luhn_check("111122223333444") == False