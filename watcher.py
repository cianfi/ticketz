#!/usr/bin/env python3
"""Notify when a clearly adjacent pair appears for Bicep at the Royal Albert Hall.

This watcher only reads public marketplace pages and sends a local notification.
It never signs in, reserves, or buys tickets.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


EVENT_DATE = "2026-11-26"
TWICKETS_URL = "https://www.twickets.live/en/event/2053116298883239936"
TICKETSWAP_URL = (
    "https://www.ticketswap.com/theatre-tickets/"
    "bicep-live-london-royal-albert-hall-2026-11-26-CasTWgohXUKoVNxiRvHLb/"
    "seats-tickets/6161819"
)
POLL_SECONDS = int(os.environ.get("TICKET_WATCH_INTERVAL", "15"))
STATE_FILE = Path(os.environ.get("TICKET_WATCH_STATE", ".ticket-watch-state.json"))


@dataclass(frozen=True)
class Listing:
    source: str
    url: str
    text: str

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.source}|{self.url}|{self.text}".encode()).hexdigest()


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _has_two_tickets(text: str) -> bool:
    patterns = (
        r"\b2\s*(?:x\s*)?(?:tickets?|seats?)\b",
        r"\b(?:tickets?|seats?)\s*[:x]?\s*2\b",
        r"\bpair\s+of\s+(?:tickets?|seats?)\b",
    )
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _has_adjacent_seats(text: str) -> bool:
    """Fail closed: require explicit consecutive seat numbers or an explicit pair claim."""
    lower = text.lower()
    if re.search(r"\b(?:side by side|seats? together|adjacent seats?)\b", lower):
        return True

    # Examples: "seats 12-13", "seat 12 & 13", "seats 12 and 13".
    for match in re.finditer(
        r"\bseats?\s*(\d{1,3})\s*(?:-|–|&|and|,)\s*(\d{1,3})\b", text, re.I
    ):
        if int(match.group(2)) == int(match.group(1)) + 1:
            return True

    # Examples: "Row G, seats 12 and 13"; also handles seat labels such as G12/G13.
    seat_ids = re.findall(r"\b(?:seat\s*)?([A-Z]{0,2}\d{1,3})\b", text, re.I)
    numbers = [int(re.search(r"\d+", seat).group()) for seat in seat_ids]
    if len(numbers) >= 2 and any(b == a + 1 for a, b in zip(numbers, numbers[1:])):
        has_row = bool(re.search(r"\brow\s+[A-Z0-9]+\b", text, re.I))
        # Letter-prefixed seat labels encode their row/section (e.g. G12, G13).
        prefixed = any(re.fullmatch(r"[A-Z]{1,2}\d{1,3}", seat, re.I) for seat in seat_ids)
        return has_row or prefixed
    return False


def qualifies(text: str) -> bool:
    return _has_two_tickets(text) and _has_adjacent_seats(text)


def _page_candidates(page, source: str, base_url: str) -> list[Listing]:
    """Collect listing-like DOM blocks, with the rendered page as a conservative fallback."""
    raw = page.evaluate(
        """() => {
          const selectors = [
            'article', '[data-testid*="ticket"]', '[data-testid*="listing"]',
            '[class*="ticket-card"]', '[class*="listing-card"]',
            '[class*="TicketCard"]', '[class*="ListingCard"]'
          ];
          const nodes = [...new Set(selectors.flatMap(s => [...document.querySelectorAll(s)]))];
          return nodes.map(node => ({
            text: (node.innerText || '').trim(),
            hrefs: [...node.querySelectorAll('a[href]')].map(a => a.href)
          })).filter(x => x.text.length > 0);
        }"""
    )
    candidates: list[Listing] = []
    for block in raw:
        text = _normalise(block["text"])
        if not text:
            continue
        hrefs = block["hrefs"] or [base_url]
        candidates.append(Listing(source, urljoin(base_url, hrefs[0]), text))

    # Some marketplace versions render a single listing in the main body rather than a card.
    if not candidates:
        body = _normalise(page.locator("body").inner_text(timeout=5000))
        candidates.append(Listing(source, base_url, body))
    return candidates


def _scan_page(browser, source: str, url: str) -> tuple[list[Listing], str | None]:
    page = browser.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        try:
            page.wait_for_load_state("networkidle", timeout=7000)
        except PlaywrightTimeoutError:
            pass
        # Allow client-rendered listings to hydrate without polling aggressively.
        page.wait_for_timeout(1500)
        text = _normalise(page.locator("body").inner_text(timeout=5000))
        if "verify you are human" in text.lower() or "access denied" in text.lower():
            return [], f"{source}: the site showed an access check; skipped this scan"
        return _page_candidates(page, source, url), None
    except Exception as exc:  # Keep one site's failure from stopping the other.
        return [], f"{source}: scan failed ({type(exc).__name__}: {exc})"
    finally:
        page.close()


def _notify(title: str, message: str, url: str) -> None:
    body = f"{message} | {url}"
    if sys.platform == "darwin":
        script = "display notification " + json.dumps(body) + " with title " + json.dumps(title)
        subprocess.run(["osascript", "-e", script], check=False)
        # Bring the matching listing to the foreground for quick manual review.
        subprocess.run(["open", url], check=False)
    else:
        print(f"\n{title}\n{body}", flush=True)


def _load_seen() -> set[str]:
    try:
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("seen", []))
    except (OSError, json.JSONDecodeError, AttributeError):
        return set()


def _save_seen(seen: Iterable[str]) -> None:
    STATE_FILE.write_text(json.dumps({"seen": sorted(seen)}, indent=2) + "\n")


def main() -> None:
    seen = _load_seen()
    print(
        f"Watching Bicep Live at Royal Albert Hall ({EVENT_DATE}) every {POLL_SECONDS}s. "
        "Only explicit pairs with adjacent seats will notify. Press Ctrl+C to stop.",
        flush=True,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            while True:
                if datetime.now(ZoneInfo("Europe/London")).date() > date.fromisoformat(EVENT_DATE):
                    print("Event date has passed; watcher stopped.", flush=True)
                    return
                now = time.strftime("%Y-%m-%d %H:%M:%S")
                for source, url in (("Twickets", TWICKETS_URL), ("TicketSwap", TICKETSWAP_URL)):
                    listings, error = _scan_page(browser, source, url)
                    if error:
                        print(f"[{now}] {error}", flush=True)
                        continue
                    matches = [listing for listing in listings if qualifies(listing.text)]
                    for listing in matches:
                        if listing.key in seen:
                            continue
                        snippet = listing.text[:240]
                        _notify(
                            f"Adjacent Bicep tickets on {source}",
                            snippet,
                            listing.url,
                        )
                        seen.add(listing.key)
                        _save_seen(seen)
                    print(f"[{now}] {source}: {len(matches)} matching listing(s)", flush=True)
                time.sleep(POLL_SECONDS)
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
