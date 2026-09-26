"""Small reusable vacancy pipeline: filter, score, format."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

from .models import RawVacancy
from .search_profiles.models import SearchProfile
from .search_profiles.relevance import count_keyword_matches, is_relevant_for_search_profile

TELEGRAM_TEXT_LIMIT = 4096
MAX_LINK_LENGTH = 1800


def _escape_limited(value: str, limit: int) -> str:
    """Escape a field without cutting an HTML entity in half."""
    escaped = escape(value)
    if len(escaped) <= limit:
        return escaped
    if limit <= 0:
        return ""
    pieces: list[str] = []
    remaining = limit - 1  # reserve one character for the ellipsis
    for char in value:
        piece = escape(char)
        if len(piece) > remaining:
            break
        pieces.append(piece)
        remaining -= len(piece)
    return "".join(pieces) + "…"


@dataclass(frozen=True)
class Criteria:
    min_score: int = 0
    min_salary: int = 0
    remote_only: bool = False


def evaluate(vacancy: RawVacancy, profile: SearchProfile, criteria: Criteria) -> int | None:
    """Return a transparent demo score, or None when a rule rejects a vacancy."""
    if not is_relevant_for_search_profile(vacancy.raw_text, profile):
        return None
    if criteria.remote_only and vacancy.remote_flag != 1:
        return None
    if criteria.min_salary and (vacancy.salary_min is None or vacancy.salary_min < criteria.min_salary):
        return None
    matches = count_keyword_matches(vacancy.raw_text, profile.heuristic_keywords)
    score = min(95, 20 + matches * 25 + (10 if vacancy.remote_flag == 1 else 0))
    return score if score >= criteria.min_score else None


def format_card(vacancy: RawVacancy, score: int, profile: SearchProfile) -> str:
    fields = (
        vacancy.title or "Вакансия",
        vacancy.company or "Компания не указана",
        vacancy.salary_text or "Зарплата не указана",
        profile.display_name,
    )
    try:
        parsed = urlparse(vacancy.url)
    except ValueError:
        parsed = None
    link = ""
    if parsed and parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.hostname.endswith(".invalid"):
        candidate = f'\n<a href="{escape(vacancy.url, quote=True)}">Открыть вакансию</a>'
        if len(candidate) <= MAX_LINK_LENGTH:
            link = candidate

    shown_score = max(0, min(100, score))

    def compose(title: str, company: str, salary: str, name: str) -> str:
        return (
            f"<b>{title}</b>\nКомпания: {company}\nЗарплата: {salary}\n"
            f"СКОРИНГ: {shown_score}/100\nПрофиль: {name}{link}\n"
            "Оценка по ключевым словам. Проверьте вакансию перед откликом."
        )

    escaped_fields = tuple(escape(value) for value in fields)
    card = compose(*escaped_fields)
    if len(card) <= TELEGRAM_TEXT_LIMIT:
        return card

    available = TELEGRAM_TEXT_LIMIT - len(compose("", "", "", ""))
    shares = (available // 2, available // 4, available // 8)
    quotas = (*shares, available - sum(shares))
    limits = [min(len(value), quota) for value, quota in zip(escaped_fields, quotas)]
    spare = available - sum(limits)
    for index, value in enumerate(escaped_fields):
        extra = min(len(value) - limits[index], spare)
        limits[index] += extra
        spare -= extra
    return compose(*(_escape_limited(value, limit) for value, limit in zip(fields, limits)))
