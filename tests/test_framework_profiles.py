"""The published skeleton must work with profiles that are not in Python code."""
from __future__ import annotations

import json
import socket
from importlib.resources import files
from pathlib import Path

import pytest

from remotejob_bot.demo import run_demo
from remotejob_bot.search_profiles.registry import load_profiles


EXAMPLE = Path(__file__).resolve().parents[1] / "profiles" / "example.json"


@pytest.mark.asyncio
async def test_two_fictional_profiles_select_different_vacancies(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("demo attempted a socket connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    designer = await run_demo(EXAMPLE, "designer")
    automation = await run_demo(EXAMPLE, "ai_automation")
    assert len(designer) == len(automation) == 1
    assert "Дизайнер макетов" in designer[0]
    assert "Специалист по автоматизации" in automation[0]
    assert "от 70 000 до 100 000 руб." in designer[0]
    assert "от 90 000 до 130 000 руб." in automation[0]


@pytest.mark.asyncio
async def test_new_profile_and_criteria_need_only_json_edit(tmp_path: Path) -> None:
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    custom = dict(example["profiles"][0])
    custom.update(key="custom_support", display_name="Поддержка", heuristic_keywords=["поддержк"])
    path = tmp_path / "mine.json"
    path.write_text(json.dumps({"profiles": [custom]}, ensure_ascii=False), encoding="utf-8")
    assert set(load_profiles(path)) == {"custom_support"}
    cards = await run_demo(path, "custom_support")
    assert len(cards) == 1 and "Специалист поддержки" in cards[0]
    assert await run_demo(path, "custom_support", remote_only=True) == []
    assert await run_demo(path, "custom_support", min_salary=100_000) == []
    assert await run_demo(path, "custom_support", min_score=96) == []


def test_invalid_config_does_not_echo_profile_text(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"profiles": [{"key": "bad key", "profile_text": "PRIVATE_VALUE"}]}', encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_profiles(path)
    assert "PRIVATE_VALUE" not in str(exc.value)


@pytest.mark.asyncio
async def test_bundled_demo_resources_work_outside_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert set(load_profiles()) == {"designer", "ai_automation"}
    cards = await run_demo(None, "ai_automation")
    assert len(cards) == 1 and "Специалист по автоматизации" in cards[0]


def test_bundled_examples_match_editable_examples() -> None:
    package = files("remotejob_bot")
    assert package.joinpath("data", "profiles", "example.json").read_text(encoding="utf-8") == EXAMPLE.read_text(encoding="utf-8")
    for name in ("design", "automation", "support"):
        assert package.joinpath("data", "fixtures", f"{name}.html").read_text(encoding="utf-8") == (EXAMPLE.parents[1] / "fixtures" / f"{name}.html").read_text(encoding="utf-8")
