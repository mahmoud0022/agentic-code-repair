from calculator import calculate_discount


def test_discount_20_percent():
    assert calculate_discount(100, 20) == 80


def test_discount_10_percent():
    assert calculate_discount(50, 10) == 45


def test_discount_25_percent():
    assert calculate_discount(200, 25) == 150
