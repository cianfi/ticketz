# Bicep ticket watcher

Watches the Twickets and TicketSwap event pages for **two tickets with explicit evidence that the seats are together** for Bicep Live at the Royal Albert Hall on Thursday 26 November 2026. When a new match appears, it sends a macOS notification and opens the listing in your default browser for you to review. It never signs in, reserves, or buys tickets.

The checker is deliberately strict: it only alerts when one listing states a pair and gives consecutive seat numbers in the same row, or explicitly says the two seats are together/adjacent. It does not treat standing tickets or two separate listings as a seated pair.

## Run it

Requires Python 3.10+ and macOS notifications. From this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python watcher.py
```

Keep the process running to receive notifications. Press `Ctrl+C` to stop it. The default polling interval is 30 seconds. To change it, set `TICKET_WATCH_INTERVAL` to a number of seconds before starting. The watcher stores already-notified listing IDs in `.ticket-watch-state.json`; remove that file if you want to receive alerts for currently listed matches again.

On non-macOS systems, matches are printed to the terminal instead of using desktop notifications.

## Notes

- The event URLs are pinned to the current event pages. If either marketplace changes its page URL or markup, the scan may need an update.
- The watcher fails closed when it cannot find clear seat adjacency information. Review the marketplace listing yourself before taking any action.
- The event's resale terms appear to restrict resale to authorised channels, with event information pointing to DICE resale. Confirm the current terms before acting on any third-party listing; unauthorised resale may put ticket validity at risk.
- Marketplace pages may limit automated access. The watcher does not bypass login checks, CAPTCHAs, or other access controls; it logs a message and skips that marketplace scan if access is blocked.
