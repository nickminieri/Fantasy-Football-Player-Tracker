"""Telegram Bot API sender.

Setup: create a bot via @BotFather to get a token, message the bot once, then
read your chat id from https://api.telegram.org/bot<token>/getUpdates
"""
from __future__ import annotations

import html
import time

import requests

API = "https://api.telegram.org"
MAX_LEN = 4096


def escape(text: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return html.escape(text or "", quote=False)


def _chunk(text: str, size: int = MAX_LEN) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > size:
            if current:
                chunks.append(current)
            # A single very long line still needs hard splitting.
            while len(line) > size:
                chunks.append(line[:size])
                line = line[size:]
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, text: str, *, disable_preview: bool = False) -> bool:
        """Send a (possibly long) HTML message. Returns True if all parts sent."""
        ok = True
        for part in _chunk(text):
            url = f"{API}/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            }
            try:
                resp = requests.post(url, json=payload, timeout=20)
                if resp.status_code == 429:
                    retry_after = resp.json().get("parameters", {}).get("retry_after", 2)
                    time.sleep(retry_after + 1)
                    resp = requests.post(url, json=payload, timeout=20)
                resp.raise_for_status()
            except requests.RequestException as exc:
                print(f"[telegram] send failed: {exc}")
                ok = False
            time.sleep(0.4)  # be gentle with Telegram's per-chat rate limit
        return ok
