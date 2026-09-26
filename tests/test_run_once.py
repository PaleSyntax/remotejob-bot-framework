"""Run-once scans local or public pages and sends only on explicit request."""
from __future__ import annotations

import json
import socket
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from remotejob_bot.pipeline import Criteria, evaluate, format_card
from remotejob_bot.models import RawVacancy
from remotejob_bot.run_once import run_once, send_telegram_card
from remotejob_bot.search_profiles.registry import load_profiles


ROOT = Path(__file__).resolve().parents[1]
PROFILE = load_profiles(ROOT / "profiles" / "example.json")["ai_automation"]


@pytest.mark.asyncio
async def test_local_html_run_once_uses_profile_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unexpected network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    cards = await run_once(PROFILE, html_path=ROOT / "fixtures" / "automation.html", criteria=Criteria(remote_only=True))
    assert len(cards) == 1
    assert "Специалист по автоматизации" in cards[0]
    assert "example.invalid" not in cards[0]
    assert await run_once(PROFILE, html_path=ROOT / "fixtures" / "design.html") == []


@pytest.mark.asyncio
async def test_public_search_run_once_with_fake_transport() -> None:
    fixture = (ROOT / "fixtures" / "automation.html").read_text(encoding="utf-8")

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            return httpx.Response(200, text='<a href="/vacancy/show/123/example-role">vacancy</a>')
        if request.url.path == "/vacancy/show/123/example-role":
            return httpx.Response(200, text=fixture)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        cards = await run_once(
            PROFILE, search_urls=("https://remote-job.ru/search?q=automation",), http_client=client
        )
    assert len(cards) == 1 and "Специалист по автоматизации" in cards[0]
    assert '<a href="https://remote-job.ru/vacancy/show/123/example-role">' in cards[0]


def test_card_escapes_external_link_and_rejects_unsafe_scheme() -> None:
    card = format_card(RawVacancy(url="https://example.org/vacancy?a=1&b=2", title="Example"), 70, PROFILE)
    assert 'href="https://example.org/vacancy?a=1&amp;b=2"' in card
    unsafe = format_card(RawVacancy(url="javascript:alert(1)", title="Example"), 70, PROFILE)
    assert "href=" not in unsafe


def test_long_card_stays_within_telegram_limit_and_keeps_html_whole() -> None:
    long_profile = replace(PROFILE, display_name="&<Имя>" * 1000)
    card = format_card(RawVacancy(
        url="https://example.org/vacancy?a=1&b=2",
        title="<script>&" * 1000,
        company="Компания & партнёры" * 1000,
        salary_text="от 100 000 до 200 000 руб." * 1000,
    ), 70, long_profile)
    assert len(card) <= 4096
    assert card.startswith("<b>&lt;script&gt;&amp;")
    assert card.count("<b>") == card.count("</b>") == 1
    assert '<a href="https://example.org/vacancy?a=1&amp;b=2">' in card
    assert "<script>" not in card
    assert not card.endswith("&")


def test_overlong_link_is_omitted_instead_of_truncated() -> None:
    card = format_card(RawVacancy(url="https://example.org/?q=" + "&x=1" * 1000, title="Example"), 70, PROFILE)
    assert len(card) <= 4096
    assert "href=" not in card


def test_min_salary_uses_known_lower_bound() -> None:
    vacancy = RawVacancy(url="https://example.org/role", raw_text="Python automation", salary_min=70_000, salary_max=100_000)
    criteria = Criteria(min_salary=90_000)
    assert evaluate(vacancy, PROFILE, criteria) is None
    assert evaluate(replace(vacancy, salary_min=90_000), PROFILE, criteria) is not None
    assert evaluate(replace(vacancy, salary_min=None), PROFILE, criteria) is None
    assert evaluate(replace(vacancy, salary_min=None, salary_max=None), PROFILE, criteria) is None
    assert evaluate(replace(vacancy, salary_min=None, salary_max=None), PROFILE, Criteria()) is not None


@pytest.mark.asyncio
async def test_telegram_transport_is_injected_and_token_is_not_in_error() -> None:
    posted: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await send_telegram_card("<b>Demo</b>", token="fake-token", chat_id="123", http_client=client)
    assert posted == [{
        "chat_id": "123", "text": "<b>Demo</b>", "parse_mode": "HTML", "disable_web_page_preview": True
    }]

    def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        with pytest.raises(RuntimeError) as exc:
            await send_telegram_card("demo", token="fake-token", chat_id="123", http_client=client)
    assert "fake-token" not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], None, "error", {"ok": False, "description": "fake-token private URL"}])
async def test_malformed_telegram_response_has_sanitized_error(payload: object) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RuntimeError) as exc:
            await send_telegram_card("demo", token="fake-token", chat_id="123", http_client=client)
    assert "fake-token" not in str(exc.value)
    assert "https://" not in str(exc.value)
