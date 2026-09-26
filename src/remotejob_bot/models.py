"""Доменные модели проекта."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RawVacancy:
    """Единый формат вакансии на выходе любого парсера.

    Парсер отдаёт единый формат; новые источники могут использовать его же.
    """

    url: str
    title: str | None = None
    source: str = ""
    company: str | None = None
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = ""  # "RUB", "USD", "EUR"
    published_at_text: str | None = None
    city: str | None = None
    remote_flag: int | None = None  # 1=remote, 0=office, None=unknown
    raw_text: str = ""
    responses_count: int | None = None
    views_count: int | None = None
    tags: list[str] = field(default_factory=list)


# Backward compat alias — existing code imports RemoteJobVacancy
RemoteJobVacancy = RawVacancy


@runtime_checkable
class VacancySource(Protocol):
    """Протокол для всех источников вакансий.

    Каждый источник реализует единый интерфейс: name + fetch().
    """

    @property
    def name(self) -> str:
        """Короткое имя источника (e.g. 'hh', 'remotejob')."""
        ...

    async def fetch(self) -> list[RawVacancy]:
        """Получить свежие вакансии из источника."""
        ...
