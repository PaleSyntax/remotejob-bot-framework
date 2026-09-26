"""Единый парсер зарплат из произвольного текста.

Поддерживает форматы:
- "от X до Y руб" / "от X до Y рублей"
- "$X-Y" / "$X - $Y"
- "Xк" / "X000"
- "от X eur" / "от X €"
- "от X,000 до Y,000 RUR"
"""
from __future__ import annotations

import re

_CURRENCY_MAP: dict[str, str] = {
    "руб": "RUB", "рублей": "RUB", "р": "RUB", "₽": "RUB",
    "rub": "RUB", "rur": "RUB",
    "$": "USD", "usd": "USD", "dollar": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR",
}

_MONEY_RE = re.compile(
    r"(\d[\d\s,.\u00A0]{0,15})\s*"
    r"(к|k|тыс\.?)?"
    r"\s*"
    r"(руб\.?|рублей|р\.?|₽|rub|rur|\$|usd|€|eur|euro)?",
    re.IGNORECASE,
)

_DOLLAR_PREFIX_RE = re.compile(r"\$\s*(\d[\d\s,.\u00A0]{0,15})(к|k|тыс\.?)?", re.IGNORECASE)

_RANGE_RE = re.compile(r"от\s+.+?до\s+", re.IGNORECASE)


def _clean_number(raw: str, suffix: str | None) -> int | None:
    """Извлечь число из строки, с учётом суффикса 'к'/'k'."""
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    val = int(digits)
    if suffix and suffix.lower() in ("к", "k", "тыс", "тыс."):
        val *= 1000
    if val < 100 or val > 100_000_000:
        return None
    return val


def _detect_currency(text: str) -> str:
    """Определить валюту из текста."""
    lower = text.lower()
    for token, currency in _CURRENCY_MAP.items():
        if token in lower:
            return currency
    return ""


def parse_salary(text: str) -> tuple[str, int | None, int | None, str]:
    """Парсит зарплату из произвольного текста.

    Returns:
        (salary_text, salary_min, salary_max, currency)

    Examples:
        >>> parse_salary("от 100 000 до 200 000 руб")
        ("от 100 000 до 200 000 руб.", 100000, 200000, "RUB")
        >>> parse_salary("$3000-5000")
        ("$3 000 – $5 000", 3000, 5000, "USD")
        >>> parse_salary("120к")
        ("от 120 000", 120000, None, "")
    """
    if not text or not text.strip():
        return "", None, None, ""

    lower = text.lower()

    # Explicit "not specified"
    if any(s in lower for s in ("з.п. не указана", "з/п не указана", "з.п не указана", "не указана")):
        return "не указана", None, None, ""

    currency = _detect_currency(text)

    # Try $-prefixed numbers first
    dollar_vals: list[int] = []
    for m in _DOLLAR_PREFIX_RE.finditer(text):
        v = _clean_number(m.group(1), m.group(2))
        if v:
            dollar_vals.append(v)
    if not currency and dollar_vals:
        currency = "USD"

    # Extract all number+suffix+currency matches
    values: list[int] = []
    for m in _MONEY_RE.finditer(text):
        v = _clean_number(m.group(1), m.group(2))
        if v:
            values.append(v)
            if not currency and m.group(3):
                currency = _CURRENCY_MAP.get(m.group(3).lower().rstrip("."), "")

    # Merge dollar values
    all_vals = list(dict.fromkeys(dollar_vals + values))  # preserve order, dedup
    # Filter reasonable salary range
    all_vals = [v for v in all_vals if 1000 <= v <= 10_000_000]

    if not all_vals:
        return "", None, None, currency

    salary_min: int | None = None
    salary_max: int | None = None

    has_from = "от" in lower or "from" in lower
    has_to = "до" in lower or "to" in lower

    if has_from and has_to and len(all_vals) >= 2:
        salary_min, salary_max = all_vals[0], all_vals[1]
        if salary_min > salary_max:
            salary_min, salary_max = salary_max, salary_min
    elif has_from:
        salary_min = all_vals[0]
    elif has_to:
        salary_max = all_vals[0]
    elif len(all_vals) >= 2:
        salary_min, salary_max = min(all_vals), max(all_vals)
    else:
        salary_min = all_vals[0]

    # Format human-readable text
    cur_suffix = f" {currency}" if currency else ""
    cur_prefix = "$" if currency == "USD" else ("€" if currency == "EUR" else "")
    parts: list[str] = []
    if salary_min and salary_max:
        if cur_prefix:
            parts.append(f"от {cur_prefix}{salary_min:,} до {cur_prefix}{salary_max:,}".replace(",", " "))
        else:
            parts.append(f"от {salary_min:,} до {salary_max:,}{cur_suffix}".replace(",", " "))
    elif salary_min:
        if cur_prefix:
            parts.append(f"от {cur_prefix}{salary_min:,}".replace(",", " "))
        else:
            parts.append(f"от {salary_min:,}{cur_suffix}".replace(",", " "))
    elif salary_max:
        if cur_prefix:
            parts.append(f"до {cur_prefix}{salary_max:,}".replace(",", " "))
        else:
            parts.append(f"до {salary_max:,}{cur_suffix}".replace(",", " "))

    salary_text = " ".join(parts) if parts else ""
    return salary_text, salary_min, salary_max, currency
