"""A small, user-configured prefilter before LLM evaluation."""
from __future__ import annotations

import re

from .models import SearchProfile


def count_keyword_matches(text: str, keywords: tuple[str, ...]) -> int:
    normalized = text.casefold()
    matches = 0
    for raw in keywords:
        keyword = raw.casefold()
        if len(keyword) < 4:
            found = re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized) is not None
        else:
            found = keyword in normalized
        matches += found
    return matches


def is_relevant_for_search_profile(text: str, profile: SearchProfile) -> bool:
    """Accept a vacancy when any configured keyword appears in its text.

    An empty keyword list disables this cheap prefilter. The LLM stage still
    evaluates the vacancy when live mode is enabled.
    """
    keywords = profile.heuristic_keywords
    if not keywords:
        return True
    return count_keyword_matches(text, keywords) > 0
