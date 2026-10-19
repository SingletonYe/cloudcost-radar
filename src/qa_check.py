#!/usr/bin/env python3
"""CloudCost Radar - publish quality gate.

Run after build_site.py. Prints PASS or FAIL with every failing check listed, and exits
non-zero on FAIL so the daily pipeline stops instead of publishing a broken site.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

REQUIRED_PATHS = [
    "/index.html", "/instances.html", "/spot.html", "/regions.html", "/cheapest.html",
    "/gpu.html", "/alternatives.html", "/calculator.html", "/pricing-changes.html",
    "/api.html", "/about.html", "/methodology.html", "/affiliate-disclosure.html",
    "/privacy.html", "/contact.html", "/sitemap.xml", "/robots.txt", "/404.html",
]

PLACEHOLDER_PATTERNS = [
    (re.compile(r"YOUR[_A-Z]*"), "unfilled placeholder value"),
    (re.compile(r"\{(?!search_term_string\})[a-z_]+\}"), "unrendered template variable"),
    (re.compile(r"\bTODO\b"), "TODO left in output"),
    (re.compile(r">\s*None\s*<"), "literal None rendered"),
    (re.compile(r">\s*undefined\s*<"), "literal undefined rendered"),
    (re.compile(r">\s*NaN\s*<"), "literal NaN rendered"),
    (re.compile(r"angelfire|example\.com/aff"), "dummy link left in output"),
]

FORBIDDEN_CLAIMS = [
    re.compile(r"guaranteed (profit|income|savings|return)", re.I),
    re.compile(r"risk[- ]free (investment|return|profit)", re.I),
    re.compile(r"get rich", re.I),
]


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def check(self, ok: bool, message: str) -> bool:
        if ok:
            self.notes.append(f"ok   {message}")
        else:
            self.failures.append(message)
        return ok

    def fail(self, message: str) -> None:
        self.failures.append(message)


def internal_targets(site: Path, href: str) -> list[Path]:
    href = href.split("#")[0].split("?")[0]
    if not href.startswith("/"):
        return []
    path = href.lstrip("/")
    if href.endswith("/"):
        return [site / path / "index.html"]
    return [site / path, site / path / "index.html"]


def check_data(report: Report) -> dict:
    inst_path = DATA / "latest" / "instances.json"
    if not report.check(inst_path.exists(), "collected instance data present"):
        return {}
    doc = json.loads(inst_path.read_text(encoding="utf-8"))
    rows = doc.get("instances", [])
    report.check(len(rows) >= 600, f"primary region has {len(rows)} instance types (>= 600)")

    bad_price = [r["type"] for r in rows if not r["od_hour"] or r["od_hour"] <= 0]
    report.check(not bad_price, f"every on-demand price is positive ({len(bad_price)} bad)")
    bad_month = [r["type"] for r in rows
                 if abs(r["od_month"] - r["od_hour"] * 730) / max(r["od_month"], 1e-9) > 0.05]
    report.check(not bad_month, f"monthly equals hourly x 730 ({len(bad_month)} inconsistent)")
    bad_spot = [r["type"] for r in rows
                if r["spot_hour"] is not None and not (0 < r["spot_hour"] <= r["od_hour"] * 2)]
    report.check(not bad_spot, f"spot prices are within 2x on-demand ({len(bad_spot)} bad)")
    report.notes.append(f"note {len([r for r in rows if r['spot_hour']])} instance types carry a spot price")

    meta_path = DATA / "latest" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    snapshot = DATA / "snapshots" / f"{doc.get('date')}.json"
    report.check(snapshot.exists(), f"snapshot for {doc.get('date')} exists (day collected once)")
    report.check(meta.get("date") == doc.get("date"), "meta date matches the instance snapshot")
    changes = DATA / "changes" / f"{doc.get('date')}.json"
    report.check(changes.exists(), "change log written for today")
    history = DATA / "history" / "spot" / f"{doc.get('date')}.json"
    report.check(history.exists(), "spot history written for today")
    return doc


def check_pages(site: Path, report: Report, base_url: str) -> None:
    for rel in REQUIRED_PATHS:
        report.check((site / rel.lstrip("/")).exists(), f"required page {rel} exists")

    pages = sorted(site.rglob("*.html"))
    report.check(len(pages) >= 800, f"{len(pages)} HTML pages generated (>= 800)")

    placeholder_hits: list[str] = []
    claim_hits: list[str] = []
    canonical_bad: list[str] = []
    missing_disclosure: list[str] = []
    titles: dict[str, str] = {}
    duplicate_titles: list[str] = []
    duplicate_desc: set[str] = set()
    desc_seen: set[str] = set()
    broken_links: set[str] = set()
    affiliate_missing_rel: list[str] = []
    sponsored_pages: set[str] = set()
    page_total_bytes = 0

    for path in pages:
        text = path.read_text(encoding="utf-8")
        page_total_bytes += len(text)
        rel = "/" + str(path.relative_to(site))

        for pattern, label in PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                placeholder_hits.append(f"{rel}: {label}")
        for pattern in FORBIDDEN_CLAIMS:
            if pattern.search(text):
                claim_hits.append(f"{rel}: {pattern.pattern}")

        title = re.search(r"<title>(.*?)</title>", text, re.S)
        desc = re.search(r'<meta name="description" content="([^"]*)"', text)
        canonical = re.search(r'<link rel="canonical" href="([^"]*)"', text)
        noindex_page = 'content="noindex' in text
        if not title or not desc or not canonical:
            canonical_bad.append(f"{rel}: missing title/description/canonical")
        else:
            title_text = title.group(1).strip()
            if title_text in titles:
                duplicate_titles.append(f"{rel} duplicates {titles[title_text]}")
            titles[title_text] = rel
            if not noindex_page:
                if len(desc.group(1)) < 40:
                    canonical_bad.append(f"{rel}: description too short")
                if desc.group(1) in desc_seen:
                    duplicate_desc.add(rel)
                desc_seen.add(desc.group(1))
            if rel == "/index.html":
                expect = base_url.rstrip("/") + "/"
            elif rel.endswith("/index.html"):
                expect = base_url.rstrip("/") + rel[:-len("index.html")]
            else:
                expect = base_url.rstrip("/") + rel
            if canonical.group(1) != expect:
                canonical_bad.append(f"{rel}: canonical {canonical.group(1)} != {expect}")

        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
            try:
                json.loads(m.group(1))
            except json.JSONDecodeError as exc:
                canonical_bad.append(f"{rel}: invalid JSON-LD ({exc})")

        for m in re.finditer(r'<a\s+([^>]*)href="(/[^"]*)"', text):
            attrs = m.group(1)
            href = m.group(2)
            targets = internal_targets(site, href)
            if targets and not any(t.exists() for t in targets):
                broken_links.add(f"{rel} -> {href}")
            if "sponsored" in attrs:
                sponsored_pages.add(rel)
                if "nofollow" not in attrs:
                    affiliate_missing_rel.append(f"{rel}: sponsored link without nofollow")

        # disclosure must appear on any page that monetises
        if re.search(r'rel="[^"]*sponsored', text) or "referral" in text.lower():
            if "affiliate-disclosure" not in text and "referral link" not in text.lower():
                missing_disclosure.append(rel)

        for m in re.finditer(r'(?:src|href)="(/assets/[^"]+)"', text):
            asset = m.group(1)
            if not (site / asset.lstrip("/")).exists():
                broken_links.add(f"{rel} -> {asset}")

    report.check(not placeholder_hits, f"no placeholder text in output ({len(placeholder_hits)} hits)")
    for hit in placeholder_hits[:10]:
        report.fail(f"  {hit}")
    report.check(not claim_hits, f"no guarantee/return claims in copy ({len(claim_hits)} hits)")
    for hit in claim_hits[:5]:
        report.fail(f"  {hit}")
    report.check(not canonical_bad, f"every page has sound SEO metadata ({len(canonical_bad)} issues)")
    for hit in canonical_bad[:10]:
        report.fail(f"  {hit}")
    report.check(not duplicate_titles, f"page titles are unique ({len(duplicate_titles)} duplicates)")
    for hit in duplicate_titles[:5]:
        report.fail(f"  {hit}")
    report.check(not duplicate_desc, f"meta descriptions are unique ({len(duplicate_desc)} duplicates)")
    report.check(not broken_links, f"no broken internal links or assets ({len(broken_links)} broken)")
    for hit in sorted(broken_links)[:10]:
        report.fail(f"  {hit}")
    report.check(not affiliate_missing_rel, f"sponsored links carry rel=nofollow ({len(affiliate_missing_rel)})")
    report.check(not missing_disclosure, f"monetised pages carry a disclosure ({len(missing_disclosure)})")
    for hit in missing_disclosure[:5]:
        report.fail(f"  {hit}")
    report.notes.append(f"note {len(sponsored_pages)} pages currently contain sponsored links")
    report.notes.append(f"note total HTML weight {page_total_bytes/1024/1024:.1f} MiB")


def check_sitemap(site: Path, report: Report, base_url: str) -> None:
    sitemap = site / "sitemap.xml"
    robots = site / "robots.txt"
    if not report.check(sitemap.exists() and robots.exists(), "sitemap.xml and robots.txt exist"):
        return
    try:
        tree = ET.fromstring(sitemap.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        report.fail(f"sitemap.xml is not valid XML: {exc}")
        return
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    locs = [el.text for el in tree.iter(f"{ns}loc")]
    report.check(len(locs) >= 800, f"sitemap lists {len(locs)} URLs")
    page_count = len(list(site.rglob("*.html"))) - 1  # 404 is noindex
    report.check(abs(len(locs) - page_count) <= 2,
                 f"sitemap URL count ({len(locs)}) matches page count ({page_count})")
    missing = []
    for loc in locs:
        parsed = urlparse(loc)
        if not loc.startswith(base_url.rstrip("/")):
            missing.append(loc)
            continue
        rel = parsed.path.lstrip("/")
        if rel in ("", "/"):
            target = site / "index.html"
        else:
            target = site / rel
        if not target.exists():
            missing.append(loc)
    report.check(not missing, f"every sitemap URL maps to a built page ({len(missing)} missing)")
    for hit in missing[:10]:
        report.fail(f"  {hit}")
    robots_text = robots.read_text(encoding="utf-8")
    report.check("Sitemap:" in robots_text, "robots.txt points at the sitemap")
    report.check("Disallow: /404.html" in robots_text, "robots.txt keeps the 404 page out of the index")


def check_config_and_ads(site: Path, report: Report) -> None:
    site_cfg = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
    aff_cfg = json.loads((ROOT / "config" / "affiliates.json").read_text(encoding="utf-8"))
    alt_cfg = json.loads((ROOT / "config" / "alternatives.json").read_text(encoding="utf-8"))

    for prog in aff_cfg.get("programs", []):
        ref = (prog.get("ref_url") or "").strip()
        report.check(not ref or "YOUR" not in ref.upper(),
                     f"affiliate program {prog['id']} has no placeholder referral URL")
    report.check(not aff_cfg.get("policy", {}).get("paid_placements_never_affect_rankings") is False,
                 "policy states paid placements never affect rankings")

    ads = site_cfg.get("ads", {})
    alternatives_html = (site / "alternatives.html").read_text(encoding="utf-8")
    if not ads.get("enabled"):
        report.check("adsbygoogle" not in alternatives_html,
                     "no ad markup is present while ads are disabled")

    index_html = (site / "index.html").read_text(encoding="utf-8")
    report.check("not affiliated with" in index_html,
                 "AWS non-affiliation notice is present in the footer")

    # Unverified provider prices must never be rendered as numbers.
    for prov in alt_cfg.get("providers", []):
        all_unverified = all(p.get("price_status") != "verified" for p in prov.get("plans", []))
        if all_unverified:
            report.check(f"see provider" in alternatives_html,
                         "unverified provider prices display as 'see provider'")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "site"))
    args = parser.parse_args()
    site = Path(args.out)
    report = Report()

    if not report.check(site.exists() and (site / "index.html").exists(),
                        "site bundle exists with an index.html"):
        print("FAIL")
        for failure in report.failures:
            print("  " + failure)
        return 1

    site_cfg = json.loads((ROOT / "config" / "site.json").read_text(encoding="utf-8"))
    base_url = site_cfg["base_url"]

    check_data(report)
    check_pages(site, report, base_url)
    check_sitemap(site, report, base_url)
    check_config_and_ads(site, report)

    if report.failures:
        print("FAIL")
        for failure in report.failures:
            print("  " + failure)
        print(f"\n{len(report.failures)} failing checks")
        return 1

    print("PASS")
    for note in report.notes:
        print("  " + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
