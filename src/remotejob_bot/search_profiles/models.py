"""Immutable application-level search-profile contract."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class SearchProfile:
    key: str
    display_name: str
    emoji: str
    profile_text: str
    heuristic_keywords: tuple[str, ...]
    enabled_sources: frozenset[str]
    remotejob_search_urls: tuple[str, ...]
    hh_search_queries: tuple[str, ...]
    eval_context: str
    pipeline_context: str
    resume_context: str
    digest_context: str
    presentation_policy: str = ""
