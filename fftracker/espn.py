"""ESPN undocumented news API.

The general NFL news feed returns articles, each tagged with the athletes it
references (in ``categories``). We fetch it once and attribute stories to
tracked players by matching ESPN athlete ids — the ``?athlete=`` query param is
unreliable (ESPN ignores it and returns the league-wide feed), so we filter
ourselves. No key required; no SLA, so callers treat failures as non-fatal.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .http import get_json

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"


@dataclass
class Article:
    headline: str
    description: str
    url: str
    published: str  # ISO 8601 string as returned by ESPN
    athlete_ids: list[str] = field(default_factory=list)
    source: str = "espn"

    def dedupe_key(self) -> str:
        return self.url or f"{self.published}|{self.headline}"


def _athlete_ids(article: dict) -> list[str]:
    ids: list[str] = []
    for cat in article.get("categories", []) or []:
        if cat.get("type") != "athlete":
            continue
        aid = cat.get("athleteId") or (cat.get("athlete") or {}).get("id")
        if aid is not None:
            ids.append(str(aid))
    return ids


def _parse_articles(payload: dict | None) -> list[Article]:
    if not payload:
        return []
    out: list[Article] = []
    for art in payload.get("articles", []) or []:
        if (art.get("type") or "").lower() == "media":
            continue
        web = (art.get("links", {}) or {}).get("web", {}) or {}
        out.append(
            Article(
                headline=(art.get("headline") or "").strip(),
                description=(art.get("description") or "").strip(),
                url=web.get("href", "") or "",
                published=art.get("published") or art.get("lastModified") or "",
                athlete_ids=_athlete_ids(art),
            )
        )
    return out


def get_recent_news(limit: int = 50, session=None) -> list[Article]:
    """Recent NFL news, each article tagged with the athlete ids it references."""
    payload = get_json(NEWS_URL, params={"limit": limit}, session=session)
    return _parse_articles(payload)
