"""Tiny demo app for the Hashimori runtime demo."""


def apply_discount(price: float, percent: float) -> float:
    """Return price after a percentage discount, rounded to cents."""
    return round(price * (1 - percent / 100), 2)  # bug: percent over 100 should clamp


def status() -> str:
    return "ok"
