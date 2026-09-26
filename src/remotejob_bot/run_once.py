"""Run one configurable scan; Telegram delivery is an explicit opt-in."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .pipeline import Criteria, evaluate, format_card
from .remotejob import RemoteJobClient
from .search_profiles.models import SearchProfile
from .search_profiles.registry import load_profiles, validate_search_profile


def _check_search_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"remote-job.ru", "www.remote-job.ru"}:
        raise ValueError("Search URL must be an HTTPS page on remote-job.ru")


async def run_once(
    profile: SearchProfile,
    *,
    html_path: str | Path | None = None,
    search_urls: tuple[str, ...] = (),
    criteria: Criteria = Criteria(),
    max_results: int = 3,
    http_client: httpx.AsyncClient | None = None,
) -> list[str]:
    """Use a saved HTML page or search remote-job.ru once, then make cards."""
    if "remotejob" not in profile.enabled_sources:
        raise ValueError("Enable 'remotejob' in the selected profile before running a scan")
    if max_results < 1 or max_results > 20:
        raise ValueError("max_results must be between 1 and 20")
    cards: list[str] = []

    if html_path is not None:
        try:
            html = Path(html_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("Cannot read the local HTML file") from exc

        async def local_response(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=html)

        async with httpx.AsyncClient(transport=httpx.MockTransport(local_response)) as client:
            vacancy = await RemoteJobClient(http_client=client).fetch_vacancy("https://example.invalid/local")
            score = evaluate(vacancy, profile, criteria)
            if score is not None:
                cards.append(format_card(vacancy, score, profile))
        return cards

    urls = search_urls or profile.remotejob_search_urls
    if not urls:
        raise ValueError("Set remotejob_search_urls in the profile or pass --search-url")
    for url in urls:
        _check_search_url(url)
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        parser = RemoteJobClient(http_client=client)
        for search_url in urls:
            vacancy_urls = await parser.list_vacancy_urls(search_url)
            if not vacancy_urls and parser.last_error:
                raise RuntimeError("Search page could not be loaded")
            for url in vacancy_urls[:max_results]:
                try:
                    vacancy = await parser.fetch_vacancy(url)
                except httpx.HTTPError:
                    continue
                score = evaluate(vacancy, profile, criteria)
                if score is not None:
                    cards.append(format_card(vacancy, score, profile))
                if len(cards) >= max_results:
                    return cards
    finally:
        if owns_client:
            await client.aclose()
    return cards


async def send_telegram_card(
    card: str, *, token: str, chat_id: str, http_client: httpx.AsyncClient
) -> None:
    """Send one card through Bot API; never include the token in an error."""
    if not token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    try:
        response = await http_client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": card, "parse_mode": "HTML", "disable_web_page_preview": True},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("Telegram did not accept the card")
    except (httpx.HTTPError, ValueError):
        raise RuntimeError("Telegram delivery failed") from None


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Один запуск поиска вакансий по своему профилю")
    parser.add_argument("--profile-file", help="your JSON profile file; bundled example is used by default")
    parser.add_argument("--profile", default="ai_automation")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--html", help="saved vacancy page, processed without network")
    inputs.add_argument("--search-url", help="remote-job.ru search page")
    parser.add_argument("--max-results", type=int, default=3)
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--min-salary", type=int, default=0)
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--telegram", action="store_true", help="send cards using credentials from env/.env")
    args = parser.parse_args(argv)
    if not 0 <= args.min_score <= 100 or args.min_salary < 0:
        parser.error("--min-score must be 0..100 and --min-salary must be nonnegative")
    try:
        profiles = load_profiles(args.profile_file)
        key = validate_search_profile(args.profile)
        if key not in profiles:
            raise ValueError(f"Profile '{key}' is not defined in the selected file")
        cards = asyncio.run(run_once(
            profiles[key], html_path=args.html,
            search_urls=(args.search_url,) if args.search_url else (),
            criteria=Criteria(args.min_score, args.min_salary, args.remote_only),
            max_results=args.max_results,
        ))
        if args.telegram:
            from dotenv import load_dotenv

            load_dotenv()
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
            if not token or not chat_id:
                raise ValueError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in env/.env")

            async def deliver() -> None:
                async with httpx.AsyncClient(timeout=15) as client:
                    for card in cards:
                        await send_telegram_card(card, token=token, chat_id=chat_id, http_client=client)

            asyncio.run(deliver())
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        parser.error(str(exc))
    print("\n\n".join(cards) if cards else "Подходящих вакансий нет.")
    return 0
