"""Load candidate profiles from user-owned JSON, without code changes."""
from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from .models import SearchProfile


ALLOWED_SOURCES = frozenset({"remotejob"})
_KEY = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")


def validate_search_profile(key: object) -> str:
    """Check a profile identifier used in the database and callback payloads."""
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError("Profile key must contain 1–40 lowercase ASCII letters, digits, _ or -")
    return key


def _string(data: dict, field: str, index: int, *, required: bool = False) -> str:
    value = data.get(field, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"profiles[{index}].{field} must be a nonempty string" if required else
                         f"profiles[{index}].{field} must be a string")
    return value.strip()


def _strings(data: dict, field: str, index: int) -> tuple[str, ...]:
    value = data.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"profiles[{index}].{field} must be a list of nonempty strings")
    return tuple(item.strip() for item in value)


def load_profiles(path: str | Path | None = None) -> dict[str, SearchProfile]:
    """Read and validate profiles without displaying their contents in errors."""
    file = Path(path) if path is not None else files("remotejob_bot").joinpath("data", "profiles", "example.json")
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("Profile file is missing. Use --profile-file or reinstall the package") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read profile file") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list) or not data["profiles"]:
        raise ValueError("Profile file must contain a nonempty profiles list")

    profiles: dict[str, SearchProfile] = {}
    for index, item in enumerate(data["profiles"]):
        if not isinstance(item, dict):
            raise ValueError(f"profiles[{index}] must be an object")
        key = validate_search_profile(_string(item, "key", index, required=True))
        if key in profiles:
            raise ValueError(f"Duplicate profile key: {key}")
        sources = frozenset(_strings(item, "enabled_sources", index))
        unknown = sources - ALLOWED_SOURCES
        if unknown:
            raise ValueError(f"profiles[{index}].enabled_sources has unknown source names")
        urls = _strings(item, "remotejob_search_urls", index)
        if any(urlparse(url).scheme not in {"https", "http"} or not urlparse(url).netloc for url in urls):
            raise ValueError(f"profiles[{index}].remotejob_search_urls must contain HTTP(S) URLs")
        profiles[key] = SearchProfile(
            key=key,
            display_name=_string(item, "display_name", index, required=True),
            emoji=_string(item, "emoji", index),
            profile_text=_string(item, "profile_text", index, required=True),
            heuristic_keywords=_strings(item, "heuristic_keywords", index),
            enabled_sources=sources,
            remotejob_search_urls=urls,
            hh_search_queries=_strings(item, "hh_search_queries", index),
            eval_context=_string(item, "eval_context", index),
            pipeline_context=_string(item, "pipeline_context", index),
            resume_context=_string(item, "resume_context", index),
            digest_context=_string(item, "digest_context", index),
            presentation_policy=_string(item, "presentation_policy", index),
        )
    return profiles


def get_search_profile(key: str, settings: object) -> SearchProfile:
    normalized = validate_search_profile(key)
    path = getattr(settings, "profile_config_path", None)
    profiles = load_profiles(path)
    try:
        return profiles[normalized]
    except KeyError as exc:
        raise ValueError(f"Profile '{normalized}' is not defined in the selected file") from exc


def get_active_search_profile(settings: object) -> SearchProfile:
    return get_search_profile(getattr(settings, "active_search_profile", "ai_automation"), settings)
