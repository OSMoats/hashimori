from src.app import apply_discount, status


def test_discount():
    assert apply_discount(100, 15) == 85.0


def test_discount_never_negative():
    assert apply_discount(100, 150) == 0.0


def test_status():
    assert status() == "ok"
