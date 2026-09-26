"""Клиент remote-job.ru: список URL вакансий + парсинг деталей."""
from __future__ import annotations

import re
from urllib.parse import urljoin

import time

import httpx
from bs4 import BeautifulSoup

from .models import RawVacancy
from .resilience import scraper_retry

# Backward compat alias
RemoteJobVacancy = RawVacancy


BASE_URL = "https://remote-job.ru"

VACANCY_PATH_RE = re.compile(r"/vacancy/show/\d+/[a-z0-9\-]+", re.IGNORECASE)

RUS_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})\b",
    re.IGNORECASE,
)

MONEY_RE = re.compile(r"(\d[\d\s]{1,10})\s*(?:руб\.?|р\.?)", re.IGNORECASE)


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def _extract_salary(text: str) -> tuple[str | None, int | None, int | None]:
    """Find one salary phrase and delegate number/range parsing to salary_parser."""
    from .salary_parser import parse_salary

    if any(marker in text.lower() for marker in ("з.п. не указана", "з/п не указана", "з.п не указана")):
        return "не указана", None, None
    phrase = re.search(
        r"(?:от\s+)?\d[\d\s\u00a0]{2,}"
        r"(?:\s*(?:до|[-–—])\s*\d[\d\s\u00a0]{2,})?"
        r"\s*(?:руб\.?|рублей|₽|RUB|RUR)\b",
        text,
        re.IGNORECASE,
    )
    if phrase is None:
        return None, None, None
    formatted, salary_min, salary_max, _currency = parse_salary(phrase.group(0))
    return (formatted.replace(" RUB", " руб.") or None), salary_min, salary_max


def _extract_views_count(text: str) -> int | None:
    m = re.search(r"количество\s+просмотров\s*:\s*(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_responses_count(text: str) -> int | None:
    patterns = [
        r"количество\s+отклик\w*\s*:\s*([\d\s]+)",
        r"отклик\w*\s*:\s*([\d\s]+)",
        r"([\d\s]+)\s*отклик\w*",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            raw = re.sub(r"\D", "", m.group(1))
            if not raw:
                continue
            return int(raw)
    return None


def _extract_company(soup: BeautifulSoup) -> str | None:
    a = soup.select_one('a[href*="companyName="]')
    if a and a.get_text(strip=True):
        return a.get_text(strip=True)
    candidates = soup.select('a[href*="/company/"]')
    for c in candidates:
        t = c.get_text(strip=True)
        if t:
            return t
    return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(strip=True)
        if t:
            return t
    title = soup.find("title")
    if title:
        t = title.get_text(strip=True)
        if t:
            return t
    return None


def _extract_published_text(full_text: str) -> str | None:
    m = RUS_DATE_RE.search(full_text)
    if m:
        return m.group(0)
    return None


def _extract_city(full_text: str) -> str | None:
    m = re.search(r"\bгород\s*:\s*([А-Яа-яA-Za-z \-]+)\b", full_text, re.IGNORECASE)
    if m:
        city = m.group(1).strip()
        if city:
            return city
    return None


def _infer_remote(full_text: str) -> int | None:
    lowered = full_text.lower()
    if "удален" in lowered or "remote" in lowered:
        return 1
    if "офис" in lowered or "гибрид" in lowered:
        return 0
    return None


class RemoteJobClient:
    def __init__(self, timeout_seconds: float = 30.0, *, http_client: httpx.AsyncClient | None = None):
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        )
        self.last_error: str | None = None
        self.last_error_at: float | None = None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_vacancy_urls(self, search_url: str) -> list[str]:
        try:
            return await self._list_vacancy_urls_inner(search_url)
        except Exception as e:
            self.last_error = repr(e)
            self.last_error_at = time.monotonic()
            return []

    @scraper_retry()
    async def _list_vacancy_urls_inner(self, search_url: str) -> list[str]:
        resp = await self._client.get(search_url)
        resp.raise_for_status()
        html = resp.text
        self.last_error = None
        self.last_error_at = None
        paths = VACANCY_PATH_RE.findall(html)
        seen: set[str] = set()
        urls: list[str] = []
        for p in paths:
            u = urljoin(BASE_URL, p)
            if u in seen:
                continue
            seen.add(u)
            urls.append(u)
        return urls

    async def fetch_vacancy(self, url: str) -> RemoteJobVacancy:
        return await self._fetch_vacancy_inner(url)

    @scraper_retry()
    async def _fetch_vacancy_inner(self, url: str) -> RemoteJobVacancy:
        resp = await self._client.get(url)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")
        full_text = _normalize_ws(soup.get_text(" ", strip=True))

        title = _extract_title(soup)
        company = _extract_company(soup)
        salary_text, salary_min, salary_max = _extract_salary(full_text)
        published_at_text = _extract_published_text(full_text)
        city = _extract_city(full_text)
        remote_flag = _infer_remote(full_text)
        views_count = _extract_views_count(full_text)
        responses_count = _extract_responses_count(full_text)

        return RawVacancy(
            url=url,
            title=title,
            source="remotejob",
            company=company,
            salary_text=salary_text,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency="RUB",
            published_at_text=published_at_text,
            city=city,
            remote_flag=remote_flag,
            views_count=views_count,
            responses_count=responses_count,
            raw_text=full_text,
        )
