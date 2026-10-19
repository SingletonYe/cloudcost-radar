#!/usr/bin/env python3
"""CloudCost Radar - daily AWS EC2 price collector.

Reads the public, keyless ec2.shop price API for every tracked region, validates the
result, and writes:

  data/latest/*.json              current state (overwritten every day)
  data/snapshots/<date>.json      permanent daily digest
  data/changes/<date>.json        permanent daily change log
  data/history/spot/<date>.json   permanent spot-price history for a watchlist
  api/v1/*.json, api/feed.xml     stable machine-readable endpoints (served via GitHub raw)

Safety rule: never fabricate, estimate or backfill a price. If validation fails the
collector writes nothing and exits non-zero, so the day is simply not published.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
API = ROOT / "api"
CACHE = ROOT / ".cache" / "raw"

SOURCE_URL = "https://ec2.shop"
USER_AGENT = "CloudCostRadar/1.0 (+https://cloudcost-radar.okou.app; daily price collector)"

# region code -> (display name, continent bucket)
REGIONS = {
    "us-east-1": ("US East (N. Virginia)", "North America"),
    "us-east-2": ("US East (Ohio)", "North America"),
    "us-west-1": ("US West (N. California)", "North America"),
    "us-west-2": ("US West (Oregon)", "North America"),
    "ca-central-1": ("Canada (Central)", "North America"),
    "sa-east-1": ("South America (Sao Paulo)", "South America"),
    "eu-west-1": ("Europe (Ireland)", "Europe"),
    "eu-west-2": ("Europe (London)", "Europe"),
    "eu-west-3": ("Europe (Paris)", "Europe"),
    "eu-central-1": ("Europe (Frankfurt)", "Europe"),
    "eu-central-2": ("Europe (Zurich)", "Europe"),
    "eu-north-1": ("Europe (Stockholm)", "Europe"),
    "eu-south-1": ("Europe (Milan)", "Europe"),
    "ap-south-1": ("Asia Pacific (Mumbai)", "Asia Pacific"),
    "ap-southeast-1": ("Asia Pacific (Singapore)", "Asia Pacific"),
    "ap-southeast-2": ("Asia Pacific (Sydney)", "Asia Pacific"),
    "ap-northeast-1": ("Asia Pacific (Tokyo)", "Asia Pacific"),
    "ap-northeast-2": ("Asia Pacific (Seoul)", "Asia Pacific"),
    "ap-northeast-3": ("Asia Pacific (Osaka)", "Asia Pacific"),
    "af-south-1": ("Africa (Cape Town)", "Africa"),
}

PRIMARY_REGION = "us-east-1"
SPOT_HISTORY_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-2",
    "eu-west-1",
    "eu-central-1",
    "ap-southeast-1",
    "ap-northeast-1",
    "ap-south-1",
]

# Families whose large/xlarge/2xlarge sizes are kept in the permanent spot history.
WATCH_FAMILIES = {
    "t2", "t3", "t3a", "t4g",
    "m5", "m5a", "m5n", "m5zn", "m6a", "m6i", "m6g", "m6id", "m7a", "m7i", "m7g",
    "c5", "c5a", "c6a", "c6i", "c6g", "c6in", "c7a", "c7i", "c7g",
    "r5", "r5a", "r6a", "r6i", "r6g", "r7a", "r7i", "r7g",
    "i3", "i3en", "i4i", "i4g", "i7i", "i7ie",
    "x2gd", "x2idn", "x2iedn", "z1d",
    "g4dn", "g5", "g6", "g6e", "g6f", "p3", "p4d", "p5",
    "inf1", "inf2", "trn1", "trn1n", "f2", "vt1",
}
WATCH_SIZES = {"large", "xlarge", "2xlarge"}

# Validation thresholds. Deliberately conservative: abort rather than publish a partial day.
MIN_INSTANCES_PRIMARY = 600
MIN_INSTANCES_REGION = 40
MIN_REGIONS_OK = 18
MIN_TOTAL_INSTANCES = 2500


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch_region(region: str, retries: int = 3, timeout: int = 45) -> dict:
    """Fetch one region's price list. No API key required."""
    url = f"{SOURCE_URL}?region={region}"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"accept": "json", "user-agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("Prices"), list):
                raise ValueError("unexpected payload shape")
            return payload
        except Exception as exc:  # noqa: BLE001 - retry any transport/parse error
            last_err = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"{region}: fetch failed after {retries} attempts: {last_err}")


def to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text or text.lower() in {"n/a", "na", "unavailable", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_memory_gb(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    number = to_float(text.split()[0].replace(",", ""))
    if number is None:
        return None
    lowered = text.lower()
    if "tib" in lowered:
        return number * 1024.0
    if "tb" in lowered:
        return number * 1000.0
    if "mib" in lowered:
        return number / 1024.0
    return number


def normalize_row(raw: dict) -> dict | None:
    """Turn one upstream row into a validated record, or None if unusable."""
    itype = str(raw.get("InstanceType") or "").strip()
    if not itype:
        return None
    vcpu = raw.get("VCPUS")
    vcpu = int(vcpu) if isinstance(vcpu, (int, float)) and vcpu else None
    mem = to_memory_gb(raw.get("Memory"))
    od = to_float(raw.get("Cost"))
    if not vcpu or not mem or od is None:
        return None
    if not (0 < od <= 200.0) or mem <= 0 or vcpu <= 0:
        return None

    monthly = to_float(raw.get("MonthlyPrice"))
    if monthly is None or abs(monthly - od * 730.0) / monthly > 0.05:
        monthly = round(od * 730.0, 3)

    spot = to_float(raw.get("SpotPrice"))
    if spot is not None and not (0 < spot <= od * 2.0):
        spot = None

    def rate(key: str) -> float | None:
        value = to_float(raw.get(key))
        if value is None or not (0 < value <= od * 3.0):
            return None
        return value

    gpu = raw.get("GPU")
    gpu_note = None
    if isinstance(gpu, dict) and gpu.get("type"):
        cores = gpu.get("core")
        gpu_note = f"{gpu['type']}" + (f" x{cores}" if cores else "")

    return {
        "type": itype,
        "family": itype.split(".")[0],
        "size": itype.split(".", 1)[1] if "." in itype else "",
        "vcpu": vcpu,
        "mem_gb": round(mem, 3),
        "storage": (raw.get("Storage") or "").strip() or None,
        "network": (raw.get("Network") or "").strip() or None,
        "gpu": gpu_note,
        "od_hour": round(od, 6),
        "od_month": round(monthly, 3),
        "spot_hour": round(spot, 6) if spot is not None else None,
        "spot_reclaim": (raw.get("SpotReclaimRate") or "").strip() or None,
        "spot_saving_pct": to_float(str(raw.get("SpotSavingRate") or "").rstrip("%")),
        "r1y_hour": rate("Reserved1yPrice"),
        "r3y_hour": rate("Reserved3yPrice"),
        "r1y_conv_hour": rate("Reserved1yConveritblePrice"),
        "r3y_conv_hour": rate("Reserved3yConveritblePrice"),
    }


def is_watchlisted(itype: str) -> bool:
    if "." not in itype:
        return False
    family, size = itype.split(".", 1)
    return family in WATCH_FAMILIES and size in WATCH_SIZES


def compact(rows: list[dict]) -> list[list]:
    """Compact array form used for daily git-tracked files (keeps the repo small)."""
    return [
        [r["type"], r["vcpu"], r["mem_gb"], r["od_hour"], r["spot_hour"]]
        for r in rows
    ]


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=False), encoding="utf-8")
    tmp.replace(path)


def pct_change(old: float | None, new: float | None) -> float | None:
    if old in (None, 0) or new is None:
        return None
    return round((new - old) / old * 100.0, 2)


def load_previous_instances() -> dict[str, dict]:
    path = DATA / "latest" / "instances.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {row["type"]: row for row in payload.get("instances", [])}


def load_previous_spot_history(today: date) -> dict[str, dict]:
    """Most recent spot history file before `today`."""
    hist = DATA / "history" / "spot"
    if not hist.exists():
        return {}
    candidates = sorted(p for p in hist.glob("*.json") if p.stem < today.isoformat())
    if not candidates:
        return {}
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {"date": payload.get("date"), "regions": payload.get("regions", {})}


def build_digest(region_rows: dict[str, list[dict]], collected_at: str) -> dict:
    digest = {"date": collected_at[:10], "collected_at": collected_at, "regions": {}}
    for region, rows in region_rows.items():
        if not rows:
            continue
        cheapest = {}
        for vcpu in (1, 2, 4, 8, 16):
            pool = [r for r in rows if r["vcpu"] == vcpu]
            if pool:
                best = min(pool, key=lambda r: r["od_hour"])
                cheapest[f"{vcpu}vcpu"] = {"type": best["type"], "od_hour": best["od_hour"]}
        spot_pool = [r for r in rows if r["spot_hour"]]
        digest["regions"][region] = {
            "count": len(rows),
            "cheapest": cheapest,
            "spot_count": len(spot_pool),
            "spot_median_hour": (
                round(sorted(r["spot_hour"] for r in spot_pool)[len(spot_pool) // 2], 6)
                if spot_pool
                else None
            ),
        }
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect today's AWS EC2 prices.")
    parser.add_argument("--if-missing", action="store_true",
                        help="Exit without touching data if today's snapshot exists.")
    parser.add_argument("--date", help="Override the collection date (YYYY-MM-DD).")
    parser.add_argument("--reuse-raw", action="store_true",
                        help="Rebuild artifacts from the cached raw responses when present.")
    parser.add_argument("--regions", help="Comma-separated region subset (testing aid).")
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    iso = today.isoformat()
    snapshot_path = DATA / "snapshots" / f"{iso}.json"

    if args.if_missing and snapshot_path.exists():
        log(f"already collected: {snapshot_path} exists - nothing to do")
        return 0

    regions = [r.strip() for r in args.regions.split(",")] if args.regions else list(REGIONS)
    unknown = [r for r in regions if r not in REGIONS]
    if unknown:
        log(f"ABORT: unknown regions requested: {unknown}")
        return 2

    cache_dir = CACHE / iso
    raw_regions: dict[str, list[dict]] = {}
    failed: list[str] = []

    for region in regions:
        cached = cache_dir / f"{region}.json"
        payload = None
        if args.reuse_raw and cached.exists():
            try:
                payload = json.loads(cached.read_text(encoding="utf-8"))
                log(f"  {region}: reusing cached raw response")
            except (OSError, json.JSONDecodeError):
                payload = None
        if payload is None:
            try:
                payload = fetch_region(region)
            except RuntimeError as exc:
                log(f"  {region}: FAILED - {exc}")
                failed.append(region)
                continue
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(payload), encoding="utf-8")

        rows = [row for row in (normalize_row(r) for r in payload.get("Prices", [])) if row]
        rows.sort(key=lambda r: r["type"])
        raw_regions[region] = rows
        log(f"  {region}: {len(rows)} instance types")

    # ---- validation gate -------------------------------------------------
    problems: list[str] = []
    if len(raw_regions) < MIN_REGIONS_OK:
        problems.append(f"only {len(raw_regions)} of {len(regions)} regions returned data")
    if failed:
        problems.append(f"regions failed: {', '.join(failed)}")
    primary_rows = raw_regions.get(PRIMARY_REGION, [])
    if len(primary_rows) < MIN_INSTANCES_PRIMARY:
        problems.append(f"{PRIMARY_REGION} returned only {len(primary_rows)} instance types "
                        f"(minimum {MIN_INSTANCES_PRIMARY})")
    for region, rows in raw_regions.items():
        if len(rows) < MIN_INSTANCES_REGION:
            problems.append(f"{region} returned only {len(rows)} instance types "
                            f"(minimum {MIN_INSTANCES_REGION})")
    total = sum(len(r) for r in raw_regions.values())
    if total < MIN_TOTAL_INSTANCES:
        problems.append(f"total instance types across regions is {total} (minimum {MIN_TOTAL_INSTANCES})")

    if problems:
        log("ABORT: upstream data failed validation, publishing nothing:")
        for problem in problems:
            log(f"  - {problem}")
        return 3

    collected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    previous = load_previous_instances()

    # ---- on-demand changes for the primary region ------------------------
    od_changes = []
    for row in primary_rows:
        old = previous.get(row["type"])
        if not old:
            continue
        if abs(old.get("od_hour", 0) - row["od_hour"]) > 1e-9:
            od_changes.append({
                "type": row["type"],
                "from": old["od_hour"],
                "to": row["od_hour"],
                "pct": pct_change(old.get("od_hour"), row["od_hour"]),
            })
    od_changes.sort(key=lambda c: abs(c["pct"] or 0), reverse=True)

    new_types = sorted(set(r["type"] for r in primary_rows) - set(previous)) if previous else []
    retired_types = sorted(set(previous) - set(r["type"] for r in primary_rows)) if previous else []

    # ---- spot watchlist history -----------------------------------------
    spot_regions: dict[str, dict[str, float]] = {}
    for region in SPOT_HISTORY_REGIONS:
        rows = raw_regions.get(region, [])
        picked = {r["type"]: r["spot_hour"] for r in rows
                  if r["spot_hour"] and is_watchlisted(r["type"])}
        if picked:
            spot_regions[region] = picked

    prev_spot = load_previous_spot_history(today)
    prev_prices = prev_spot.get("regions", {})
    spot_movers = []
    for region, picked in spot_regions.items():
        before = prev_prices.get(region, {})
        for itype, price in picked.items():
            old = before.get(itype)
            change = pct_change(old, price)
            if change is None or abs(change) < 1.0:
                continue
            spot_movers.append({
                "region": region, "type": itype, "from": old, "to": price, "pct": change,
            })
    spot_movers.sort(key=lambda m: abs(m["pct"]), reverse=True)
    spot_movers = spot_movers[:120]

    # ---- write the permanent daily files --------------------------------
    changes_payload = {
        "date": iso,
        "primary_region": PRIMARY_REGION,
        "on_demand_changes": od_changes,
        "new_instance_types": new_types,
        "retired_instance_types": retired_types,
        "spot_movers": spot_movers,
        "compared_against": prev_spot.get("date"),
    }
    write_json(DATA / "changes" / f"{iso}.json", changes_payload)

    write_json(DATA / "history" / "spot" / f"{iso}.json", {
        "date": iso,
        "collected_at": collected_at,
        "regions": spot_regions,
    })

    digest = build_digest(raw_regions, collected_at)
    write_json(snapshot_path, digest)

    # ---- current state (overwritten daily) ------------------------------
    write_json(DATA / "latest" / "instances.json", {
        "date": iso,
        "collected_at": collected_at,
        "region": PRIMARY_REGION,
        "region_name": REGIONS[PRIMARY_REGION][0],
        "source": SOURCE_URL,
        "instances": primary_rows,
    })

    write_json(DATA / "latest" / "regions.json", {
        "date": iso,
        "collected_at": collected_at,
        "source": SOURCE_URL,
        "regions": {
            region: {"name": REGIONS[region][0], "bucket": REGIONS[region][1],
                     "rows": [[r["type"], r["vcpu"], r["mem_gb"], r["od_hour"], r["spot_hour"]]
                              for r in rows]}
            for region, rows in raw_regions.items()
        },
    })

    write_json(DATA / "latest" / "meta.json", {
        "date": iso,
        "collected_at": collected_at,
        "source": SOURCE_URL,
        "primary_region": PRIMARY_REGION,
        "regions_tracked": len(raw_regions),
        "instance_types_primary": len(primary_rows),
        "instance_types_total": total,
        "on_demand_changes": len(od_changes),
        "new_instance_types": len(new_types),
        "retired_instance_types": len(retired_types),
        "spot_movers": len(spot_movers),
        "spot_history_regions": sorted(spot_regions),
    })

    # ---- stable machine-readable endpoints (published through GitHub raw)
    api_rows = [
        {"type": r["type"], "vcpu": r["vcpu"], "ram_gb": r["mem_gb"], "gpu": r["gpu"],
         "on_demand_hour": r["od_hour"], "on_demand_month": r["od_month"],
         "spot_hour": r["spot_hour"], "reserved_1y_hour": r["r1y_hour"],
         "reserved_3y_hour": r["r3y_hour"]}
        for r in primary_rows
    ]
    write_json(API / "v1" / "latest.json", {
        "updated": iso,
        "collected_at": collected_at,
        "region": PRIMARY_REGION,
        "source": SOURCE_URL,
        "license": "Published provider pricing data, free to reuse with attribution.",
        "count": len(api_rows),
        "instances": api_rows,
    })
    write_json(API / "v1" / "changes.json", changes_payload)
    write_json(API / "v1" / "regions.json", {
        "updated": iso,
        "collected_at": collected_at,
        "count": len(raw_regions),
        "regions": {r: {"name": REGIONS[r][0], "instance_types": len(rows)}
                    for r, rows in raw_regions.items()},
    })

    log(f"collected {iso}: {len(primary_rows)} types in {PRIMARY_REGION}, "
        f"{total} across {len(raw_regions)} regions, "
        f"{len(od_changes)} on-demand changes, {len(new_types)} new, "
        f"{len(retired_types)} retired, {len(spot_movers)} spot movers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
