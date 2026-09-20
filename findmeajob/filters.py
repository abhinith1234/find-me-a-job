"""Deterministic filter that runs BEFORE any LLM call.

This is the whole cost story: ~2000 raw jobs -> ~40 candidates for ~0 rupees,
so Claude only ever reads jobs that already passed title + location + freshness.
"""
from __future__ import annotations

import re
from functools import lru_cache
from datetime import datetime, timedelta, timezone

from .sources import Job

REMOTE_HINTS = ("remote", "anywhere", "work from home", "wfh")
HYBRID_HINTS = ("hybrid",)
INDIA_LOCATION_HINTS = (
    "india",
    "bangalore",
    "bengaluru",
    "hyderabad",
    "pune",
    "mumbai",
    "delhi",
    "new delhi",
    "gurugram",
    "gurgaon",
    "noida",
    "chennai",
    "kolkata",
    "ahmedabad",
    "jaipur",
    "kochi",
    "coimbatore",
    "visakhapatnam",
    "trivandrum",
    "thiruvananthapuram",
    "ncr",
)


@lru_cache(maxsize=1)
def _geonames_locations() -> tuple[dict[str, set[str]], dict[str, str]]:
    """Return country -> city names and normalized city -> country mappings."""
    try:
        import geonamescache
    except ImportError:
        return {}, {}
    cache = geonamescache.GeonamesCache()
    countries = {str(row.get("name", "")).lower(): code
                 for code, row in cache.get_countries().items()}
    cities_by_country: dict[str, set[str]] = {}
    city_country: dict[str, str] = {}
    for city in cache.get_cities().values():
        name = str(city.get("name", "")).lower().strip()
        code = str(city.get("countrycode", "")).lower()
        if name and code:
            cities_by_country.setdefault(code, set()).add(name)
            city_country.setdefault(name, code)
    return {name: cities_by_country.get(code, set()) for name, code in countries.items()}, city_country


def _location_matches(location: str, selected: list[str]) -> bool:
    """Match selected cities/countries against global job location text."""
    hay = location.lower()
    countries, city_country = _geonames_locations()
    def contains_place(place: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(place)}(?!\w)", hay))

    for choice in selected:
        value = choice.lower().strip()
        if contains_place(value):
            return True
        for country, cities in countries.items():
            if value == country and any(contains_place(city) for city in cities):
                return True
        if value in city_country and contains_place(value):
            return True
    return False


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.fromisoformat(v) if fmt is None else datetime.strptime(v, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def prefilter(jobs: list[Job], cfg: dict) -> list[Job]:
    inc = cfg.get("include_titles") or [r"."]
    exc = cfg.get("exclude_titles") or []
    profile_titles = [str(title).lower() for title in cfg.get("profile_titles", [])]
    profile_seniority = str(cfg.get("profile_seniority", "")).lower()
    active_excludes = [pattern for pattern in exc if not any(
        _any_match([pattern], title) for title in profile_titles)]
    if profile_seniority in {"senior", "staff"}:
        active_excludes = [p for p in active_excludes if not re.search(
            r"staff|principal|distinguished|fellow|senior", p, re.I)]
    locs = [l.lower() for l in (cfg.get("locations") or [])]
    allow_remote = bool(cfg.get("allow_remote", True))
    workplace_types = set(cfg.get("workplace_types") or {"remote", "hybrid", "onsite"})
    preferred = [p.lower() for p in (cfg.get("preferred_locations") or []) if p]
    max_age = cfg.get("max_age_days")
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age) if max_age else None

    kept, stats = [], {"title": 0, "location": 0, "age": 0}
    for j in jobs:
        location_hay = j.location.lower()
        hay = f"{location_hay} {j.title} {j.description}".lower()
        is_remote = any(h in hay for h in REMOTE_HINTS)
        hay = f"{j.location} {j.title} {j.description}".lower()
        is_hybrid = any(h in hay for h in HYBRID_HINTS)
        is_onsite = not is_remote and not is_hybrid
        workplace_ok = (("remote" in workplace_types and is_remote)
                        or ("hybrid" in workplace_types and is_hybrid)
                        or ("onsite" in workplace_types and is_onsite))
        if not workplace_ok:
            stats["location"] += 1
            continue

        if locs:
            if is_remote and not allow_remote:
                stats["location"] += 1
                continue
            in_india = any(h in location_hay for h in INDIA_LOCATION_HINTS)
            selected_location = _location_matches(j.location, locs)
            if not is_remote and not in_india and not selected_location:
                stats["location"] += 1
                continue

        if not _any_match(inc, j.title) or (
            active_excludes and _any_match(active_excludes, j.title)):
            stats["title"] += 1
            continue

        if cutoff:
            posted = _parse_date(j.posted_at)
            if posted and posted < cutoff:
                stats["age"] += 1
                continue

        kept.append(j)

    if preferred:
        def location_priority(job: Job) -> int:
            hay = job.location.lower()
            return 0 if any(place in hay for place in preferred) else 1
        kept.sort(key=location_priority)

    summary = (f"  prefilter: {len(jobs)} -> {len(kept)} "
               f"(dropped title={stats['title']} location={stats['location']} "
               f"stale={stats['age']})")
    print(summary)
    print(f"  workplace allowed: {', '.join(sorted(workplace_types))}")
    return kept
