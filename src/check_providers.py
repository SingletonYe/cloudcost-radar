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
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "providers"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36 CloudCostRadar/1.0")


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
        digest = hashlib.sha256(body).hexdigest()[:16] if body else None
        old = previous.get(pid, {})
        changed = bool(digest and old.get("sha256") and digest != old.get("sha256"))
        entry = {
            "url": url,
            "http": result,
            "sha256": digest,
            "last_checked": today,
            "first_seen": old.get("first_seen") or today,
            "last_changed": today if changed or not old.get("sha256") else old.get("last_changed"),
            "needs_price_review": bool(changed or old.get("needs_price_review")),
        }
        status[pid] = entry
        if changed:
            changes.append({"provider": pid, "url": url, "detected": today,
                            "previous_sha256": old.get("sha256"), "current_sha256": digest})
        print(f"  {pid:14s} {result:10s} hash={digest or '-':16s}"
              f"{' CHANGED - re-verify published price' if changed else ''}")

    DATA.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit = {"date": today, "checked": len(status),
             "unreachable": [p for p, e in status.items() if not e["http"].startswith("ok")],
             "changes": changes}
    (DATA / f"audit-{today}.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")

    print(f"checked {len(status)} provider pages, {len(changes)} changed, "
          f"{len(audit['unreachable'])} unreachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
