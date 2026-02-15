import pytest
from filters import check_card

def test_is_card():
    assert check_card("5488 5500 4199 3308") == True
    assert check_card("5488550041993308") == True
    assert check_card("5488-5500-4199-3308") == True
    assert check_card("5488.5500.4199.3308") == True
    assert check_card("5488?5500?4199?3308") == True
    assert check_card("5488,5500,4199,3308") == True
    assert check_card("54 88 55 00 41 99 33 08") == True
    assert check_card("54-88-55-00-41,99.33/08") == True
    assert check_card("5 4 8 8 5 5 0 0 4 1 9 9 3 3 0 8") == True
    assert check_card("5.4-8/8*5 5 0 0 4 1 9 9 3 3 0 8") == True
    assert check_card("Збір4441111013726595") == True
    assert check_card("Збір44 411110 13726 595") == True
    assert check_card("Збір44 411110 13726 595коштів") == True
    assert check_card("Збір 44 411110 13726 595 коштів") == True
    #
    assert check_card("Збір 44 411110 13726 59 коштів") == False
    assert check_card("44 411110 13726 59 коштів") == False
    assert check_card("444111101372659 коштів") == False


