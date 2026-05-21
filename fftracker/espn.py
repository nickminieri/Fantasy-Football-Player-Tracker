"""ESPN undocumented news API.

Per-player news: site.api.espn.com/.../nfl/news?athlete={espn_id}
No key required. No SLA — endpoints can change without notice, so callers
should treat failures as non-fatal.
"""
from __future__ import annotations

from dataclasses import dataclass

from .http import get_json

NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"


@dataclass
class Article:
    headline: str
    description: str
    url: str
    published: str  # ISO 8601 string as returned by ESPN
    source: str = "espn"

    def dedupe_key(self) -> str:
        return self.url or f"{self.published}|{self.headline}"


def _parse_articles(payload: dict | None) -> list[Article]:
    if not payload:
        return []
    out: list[Article] = []
    for art in payload.get("articles", []) or []:
        if art.get("type") in {"Media", "media"}:
            continue
        links = art.get("links", {}) or {}
        web = links.get("web", {}) or {}
        url = web.get("href", "") or ""
        out.append(
            Article(
                headline=(art.get("headline") or "").strip(),
                description=(art.get("description") or "").strip(),
                url=url,
                published=art.get("published") or art.get("lastModified") or "",
            )
        )
    return out


def get_player_news(espn_id: str | int, limit: int = 10,
                    session=None) -> list[Article]:
    """Recent news articles mentioning a given ESPN athlete id."""
    if not espn_id:
        return []
    payload = get_json(
        NEWS_URL, params={"athlete": str(espn_id), "limit": limit}, session=session
    )
    return _parse_articles(payload)


def get_league_news(limit: int = 25, session=None) -> list[Article]:
    """General NFL headlines (fallback / league-wide context)."""
    payload = get_json(NEWS_URL, params={"limit": limit}, session=session)
    return _parse_articles(payload)
