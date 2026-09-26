"""Offline example: real vacancy parser, configurable profile, no credentials."""
from __future__ import annotations

import argparse
import asyncio
import sys
from importlib.resources import files
from pathlib import Path

import httpx

from .remotejob import RemoteJobClient
from .pipeline import Criteria, evaluate, format_card
from .search_profiles.registry import load_profiles, validate_search_profile


FIXTURES = ("design", "automation", "support")


async def run_demo(
    profile_path: str | Path | None,
    profile_key: str,
    *,
    min_score: int = 0,
    min_salary: int = 0,
    remote_only: bool = False,
) -> list[str]:
    """Parse bundled HTML via MockTransport and return selected cards."""
    profiles = load_profiles(profile_path)
    key = validate_search_profile(profile_key)
    if key not in profiles:
        raise ValueError(f"Profile '{key}' is not defined in the selected file")
    profile = profiles[key]
    if "remotejob" not in profile.enabled_sources:
        return []
    fixture_html = {
        name: files("remotejob_bot").joinpath("data", "fixtures", f"{name}.html").read_text(encoding="utf-8")
        for name in FIXTURES
    }

    def respond(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, text=fixture_html[name]) if name in fixture_html else httpx.Response(404)

    cards: list[str] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        parser = RemoteJobClient(http_client=client)
        for name in FIXTURES:
            vacancy = await parser.fetch_vacancy(f"https://example.invalid/vacancy/{name}")
            score = evaluate(vacancy, profile, Criteria(min_score, min_salary, remote_only))
            if score is not None:
                cards.append(format_card(vacancy, score, profile))
    return cards


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Офлайн-демо без Telegram, сети и токенов")
    parser.add_argument("--demo", action="store_true", help="run the bundled offline demo")
    parser.add_argument("--profile-file", help="your JSON profile file; bundled example is used by default")
    parser.add_argument("--profile", default="ai_automation")
    parser.add_argument("--min-score", type=int, default=0)
    parser.add_argument("--min-salary", type=int, default=0)
    parser.add_argument("--remote-only", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.min_score <= 100 or args.min_salary < 0:
        parser.error("--min-score must be 0..100 and --min-salary must be nonnegative")
    try:
        cards = asyncio.run(run_demo(
            args.profile_file, args.profile,
            min_score=args.min_score, min_salary=args.min_salary, remote_only=args.remote_only,
        ))
    except ValueError as exc:
        parser.error(str(exc))
    print("\n\n".join(cards) if cards else "Подходящих вакансий в демонстрационных примерах нет.")
    return 0
