#!/usr/bin/env python3
"""CloudCost Radar - provider pricing page drift checker.

The comparison catalog in config/alternatives.json holds prices that were read from provider
pricing pages on a stated date. Prices there are never auto-overwritten: this script fetches each
provider page, hashes it, and flags a change so a human (or the agent workflow) re-verifies the
published price instead of trusting a stale number.

Informational by design: it always exits 0 so a provider blocking the fetch never blocks the
daily price publish.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "providers"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36 CloudCostRadar/1.0")

SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
WS_RE = re.compile(r"\s+")
PRICE_RE = re.compile(r"[$€£]\s?\d[\d.,]*")


def normalize(body: bytes) -> str:
    """Strip scripts/styles and collapse whitespace so per-request noise (tokens, ads, inline
    state) does not look like a price change."""
    text = body.decode("utf-8", errors="ignore")
    text = SCRIPT_RE.sub(" ", text)
    return WS_RE.sub(" ", text).strip()


def price_tokens(normalized: str) -> list[str]:
    """The money-like strings on the page: the signal that actually matters."""
    tokens = {match.group(0).replace(" ", "").rstrip(".,") for match in PRICE_RE.finditer(normalized)}
    return sorted(tokens)


def fetch(url: str, timeout: int = 30) -> tuple[str, bytes | None]:
    try:
        req = urllib.request.Request(url, headers={"user-agent": USER_AGENT,
                                                   "accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return f"ok:{resp.status}", resp.read()
    except urllib.error.HTTPError as exc:
        return f"http_{exc.code}", None
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}", None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Override the check date (YYYY-MM-DD).")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    today = args.date or now.date().isoformat()
    catalog = json.loads((ROOT / "config" / "alternatives.json").read_text(encoding="utf-8"))
    status_path = DATA / "status.json"
    previous = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}

    status: dict[str, dict] = {}
    changes: list[dict] = []
    for prov in catalog.get("providers", []):
        pid = prov["id"]
        url = prov["verify_url"]
        result, body = fetch(url)
        normalized = normalize(body) if body else ""
        digest = hashlib.sha256(normalized.encode()).hexdigest()[:16] if normalized else None
        tokens = price_tokens(normalized) if normalized else []
        token_hash = hashlib.sha256("|".join(tokens).encode()).hexdigest()[:16] if tokens else None
        old = previous.get(pid, {})
        body_changed = bool(digest and old.get("normalized_sha256") and digest != old["normalized_sha256"])
        # Fall back to the older key name so the first run after this change still compares correctly.
        if not body_changed and digest and old.get("sha256") and digest != old["sha256"]:
            body_changed = True
        prices_changed = bool(token_hash and old.get("price_tokens_sha256")
                              and token_hash != old["price_tokens_sha256"])
        entry = {
            "url": url,
            "http": result,
            "normalized_sha256": digest,
            "price_tokens_sha256": token_hash,
            "price_token_count": len(tokens),
            "last_checked": today,
            "first_seen": old.get("first_seen") or today,
            "last_body_change": today if body_changed else old.get("last_body_change"),
            "last_price_change": today if prices_changed else old.get("last_price_change"),
            "needs_price_review": bool(prices_changed or old.get("needs_price_review")),
        }
        status[pid] = entry
        if prices_changed:
            changes.append({"provider": pid, "url": url, "detected": today,
                            "reason": "price tokens changed",
                            "previous_tokens": old.get("price_token_count"),
                            "current_tokens": len(tokens)})
        flag = "PRICES CHANGED - re-verify published price before trusting the catalog" if prices_changed \
            else ("page changed, prices identical" if body_changed else "")
        print(f"  {pid:14s} {result:10s} tokens={len(tokens):4d} "
              f"hash={token_hash or '-':16s}{flag}")

    DATA.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit = {"date": today, "checked": len(status),
             "unreachable": [p for p, e in status.items() if not e["http"].startswith("ok")],
             "changes": changes}
    (DATA / f"audit-{today}.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    print(f"checked {len(status)} provider pages, {len(changes)} with changed prices, "
          f"{len(audit['unreachable'])} unreachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
