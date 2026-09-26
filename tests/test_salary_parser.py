"""Tests for the salary_parser module.

Run:  python -m pytest tests/test_salary_parser.py -v
From: remotejob-bot/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src/ is importable (no pyproject.toml / editable install)
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from remotejob_bot.salary_parser import parse_salary


class TestParseSalaryRange:
    """Tests for 'from X to Y' patterns with explicit range markers."""

    def test_russian_range_rub(self):
        """'от 100 000 до 200 000 руб' -> min=100000, max=200000, currency=RUB."""
        salary_text, sal_min, sal_max, cur = parse_salary("от 100 000 до 200 000 руб")
        assert sal_min == 100_000
        assert sal_max == 200_000
        assert cur == "RUB"

    def test_usd_range_with_keyword(self):
        """'от 3000 до 5000 USD' -> min=3000, max=5000, currency=USD."""
        salary_text, sal_min, sal_max, cur = parse_salary("от 3000 до 5000 USD")
        assert sal_min == 3_000
        assert sal_max == 5_000
        assert cur == "USD"


class TestParseSalaryDollarPrefix:
    """Tests for $-prefixed salary strings."""

    def test_dollar_dash_range(self):
        """'$3000-5000' -> min=3000, max=5000, currency=USD."""
        salary_text, sal_min, sal_max, cur = parse_salary("$3000-5000")
        assert sal_min == 3_000
        assert sal_max == 5_000
        assert cur == "USD"

    def test_dollar_range_with_commas_and_spaces(self):
        """'$2,500 - $4,000' -> min=2500, max=4000, currency=USD."""
        salary_text, sal_min, sal_max, cur = parse_salary("$2,500 - $4,000")
        assert sal_min == 2_500
        assert sal_max == 4_000
        assert cur == "USD"


class TestParseSalarySuffix:
    """Tests for 'к'/'k' suffix shorthand."""

    def test_k_suffix_russian(self):
        """'120к' -> min=120000, max=None."""
        salary_text, sal_min, sal_max, cur = parse_salary("120к")
        assert sal_min == 120_000
        assert sal_max is None


class TestParseSalaryOneDirection:
    """Tests for 'от X' (min-only) and 'до X' (max-only) patterns."""

    def test_from_only_eur(self):
        """'от 50 000 eur' -> min=50000, currency=EUR."""
        salary_text, sal_min, sal_max, cur = parse_salary("от 50 000 eur")
        assert sal_min == 50_000
        assert cur == "EUR"

    def test_from_only_rub(self):
        """'от 80000 рублей' -> min=80000, currency=RUB."""
        salary_text, sal_min, sal_max, cur = parse_salary("от 80000 рублей")
        assert sal_min == 80_000
        assert cur == "RUB"

    def test_to_only_rub(self):
        """'до 300 000 руб' -> max=300000, currency=RUB."""
        salary_text, sal_min, sal_max, cur = parse_salary("до 300 000 руб")
        assert sal_min is None
        assert sal_max == 300_000
        assert cur == "RUB"


class TestParseSalaryNotSpecified:
    """Tests for empty / 'not specified' inputs."""

    def test_not_specified_russian(self):
        """'з/п не указана' -> (salary_text, None, None).

        """
        result = parse_salary("з/п не указана")
        assert result == ("не указана", None, None, "")

    def test_empty_string(self):
        """'' -> ('', None, None, '')."""
        salary_text, sal_min, sal_max, cur = parse_salary("")
        assert salary_text == ""
        assert sal_min is None
        assert sal_max is None
        assert cur == ""


class TestParseSalaryFormattedText:
    """Verify that the human-readable salary_text is reasonable."""

    def test_range_text_contains_both_bounds(self):
        salary_text, sal_min, sal_max, cur = parse_salary("от 100 000 до 200 000 руб")
        assert "100" in salary_text
        assert "200" in salary_text

    def test_dollar_range_text_has_dollar_sign(self):
        salary_text, sal_min, sal_max, cur = parse_salary("$3000-5000")
        assert "$" in salary_text

    def test_to_only_text_starts_with_до(self):
        salary_text, sal_min, sal_max, cur = parse_salary("до 300 000 руб")
        assert salary_text.startswith("до")
