#!/usr/bin/env python3
"""CloudCost Radar - page generators. Run as: python3 src/build_site.py --out site"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from site_base import (  # noqa: E402
    COMPARE_PAGES, DATA, DEFAULT_OUT, ROOT, SPEC_PAGES, Builder, esc, human_date,
    human_date_short, is_watchlisted, pct, usd, usd_precise,
)


def hourly(value) -> str:
    return usd_precise(value) if value is not None else "n/a"


def monthly_from_hour(value) -> str:
    return usd(value * 730) if value is not None else "n/a"


# --------------------------------------------------------------------------- home

def build_home(b: Builder) -> None:
    changes = json.loads((DATA / "changes" / f"{b.today}.json").read_text(encoding="utf-8")) \
        if (DATA / "changes" / f"{b.today}.json").exists() else {}
    movers = [m for m in (changes.get("spot_movers") or []) if m["pct"] < 0][:10]

    stats = "".join([
        b.stat("Snapshot", esc(human_date_short(b.today)), "collected daily at 06:00 UTC"),
        b.stat("Instance types", f"{(b.meta.get('instance_types_total') or 0):,}",
               f"{len(b.rows):,} in US East (N. Virginia)"),
        b.stat("Regions", str(b.meta.get("regions_tracked") or 0), "on-demand + spot prices"),
        b.stat("On-demand changes", str(b.meta.get("on_demand_changes") or 0), "vs. yesterday"),
        b.stat("Spot movers", str(b.meta.get("spot_movers") or 0), "moves of 1% or more"),
    ])

    mover_rows = []
    for m in movers:
        mover_rows.append([
            f'<a href="/instances/{esc(m["type"])}/">{esc(m["type"])}</a>',
            f'<span class="muted small">{esc(m["region"])}</span>',
            f'<span class="num">{hourly(m["from"])}</span>',
            f'<span class="num">{hourly(m["to"])}</span>',
            f'<span class="down">{esc(pct(m["pct"]))}</span>',
        ])
    mover_table = (
        b.table([("Instance", False), ("Region", False), ("Yesterday", True), ("Today", True),
                 ("Change", True)], mover_rows)
        if mover_rows else
        '<p class="muted">No spot move of 1% or more was recorded in the last collection. '
        'The spot tables below still show today\'s live prices.</p>'
    )

    picks = []
    for vcpu, ram in ((2, 4), (4, 8), (8, 16), (16, 32)):
        best = b.cheapest(vcpu=vcpu, min_mem=ram, limit=1)
        if not best:
            continue
        row = best[0]
        picks.append([
            esc(f"{vcpu} vCPU / {ram} GB"),
            f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
            f'<span class="num">{esc(str(row["mem_gb"]).rstrip("0").rstrip("."))} GB</span>',
            f'<span class="num">{hourly(row["od_hour"])}</span>',
            f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>',
            f'<span class="num">{hourly(row["spot_hour"]) if row["spot_hour"] else "n/a"}</span>',
        ])
    pick_table = b.table([("Size", False), ("Cheapest instance", False), ("RAM", True),
                          ("On-demand /hr", True), ("On-demand /mo", True), ("Spot /hr", True)],
                         picks)

    gpu_rows = []
    for row in b.cheapest(gpu_only=True, limit=5):
        gpu_rows.append([
            f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
            esc(row.get("gpu") or ""),
            f'<span class="num">{row["vcpu"]}</span>',
            f'<span class="num">{esc(str(row["mem_gb"]).rstrip("0").rstrip("."))}</span>',
            f'<span class="num">{hourly(row["od_hour"])}</span>',
            f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>',
        ])
    gpu_table = b.table([("Instance", False), ("Accelerator", False), ("vCPU", True),
                         ("RAM GB", True), ("On-demand /hr", True), ("On-demand /mo", True)],
                        gpu_rows)

    alt_cards = []
    for prov in b.alternatives.get("providers", [])[:4]:
        verified = [p for p in prov.get("plans", []) if p.get("price_status") == "verified"]
        if verified:
            cheapest = min(verified, key=lambda p: p["price_usd_month"])
            line = (f'From <strong>{usd(cheapest["price_usd_month"])}/mo</strong> for '
                    f'{cheapest["vcpu"]} vCPU / {cheapest["ram_gb"]} GB')
        else:
            line = "Live pricing on the provider site"
        alt_cards.append(
            f'<div class="card"><h3>{esc(prov["name"])}</h3><p class="small muted">{esc(prov.get("notes",""))}</p>'
            f'<p>{line}</p>'
            f'<div class="btnrow">{b.provider_link(prov["id"], prov["verify_url"], "See pricing")}</div></div>'
        )

    body = f"""
<h1>AWS compute prices, tracked every day — with the cheaper alternatives that beat them</h1>
<p class="lede">CloudCost Radar reads published AWS EC2 pricing for on-demand, spot, 1-year and
3-year reserved capacity across {b.meta.get('regions_tracked')} regions, diffes it against yesterday,
and puts it next to the cloud and VPS providers that cost less for the same job. The data is free,
the history is permanent, and every number on this page is the list price as published
on {esc(human_date(b.today))}.</p>
<div class="grid c4" style="margin:20px 0">{stats}</div>
{b.ad_slot('home_top')}
<h2>Today's biggest spot price drops</h2>
<p class="muted">Spot capacity is the same hardware at a discount, with the risk that AWS reclaims it.
These are the largest drops recorded between the last two collections.</p>
{mover_table}
<h2>Cheapest AWS instance for each size class</h2>
{pick_table}
<div class="btnrow"><a class="btn" href="/instances/">All {len(b.rows):,} instance prices</a>
<a class="btn ghost" href="/spot/">Spot price tracker</a></div>
<h2>Run the numbers before you renew</h2>
<p class="muted">Most AWS bills are bigger than they need to be because the workload sits on the wrong
purchase model — on-demand for something that runs all year, or reserved capacity for something that
runs twice a month. This calculator compares the options using today's published prices.</p>
<section class="card" id="calculator">
  <div class="grid c4">
    <div><label for="calc-vcpu">vCPU</label>
      <select id="calc-vcpu"><option>1</option><option selected>2</option><option>4</option>
      <option>8</option><option>16</option><option>32</option></select></div>
    <div><label for="calc-ram">Minimum RAM (GB)</label>
      <select id="calc-ram"><option>2</option><option selected>4</option><option>8</option>
      <option>16</option><option>32</option><option>64</option></select></div>
    <div><label for="calc-count">Instances</label>
      <select id="calc-count"><option selected>1</option><option>2</option><option>3</option>
      <option>5</option><option>10</option><option>20</option></select></div>
  </div>
  <div id="calc-out" class="calc-out" style="margin-top:16px"></div>
  <p class="small muted">Want the long version, including what a cheaper provider would charge for the
  same spec? <a href="/calculator/">Open the cloud cost calculator</a>.</p>
</section>
<h2>Is AWS actually the cheapest option?</h2>
<p class="muted">For steady-state workloads — web apps, APIs, queues, databases that run all month —
managed VPS and cloud providers are frequently the cheapest way to buy the same vCPU and RAM.
Here is what each provider charges today, with the numbers we could verify from their published
pricing pages.</p>
<div class="grid c2" style="margin-top:14px">{''.join(alt_cards)}</div>
<div class="btnrow"><a class="btn" href="/alternatives/">Compare all alternatives</a>
<a class="btn ghost" href="/gpu/">Cheapest GPU instances</a></div>
<h2>Cheapest GPU compute on AWS today</h2>
{gpu_table}
<div class="btnrow"><a class="btn ghost" href="/gpu/">All GPU instance pricing</a></div>
{b.change_rows(changes) if changes else ''}
<h2>How this page is produced</h2>
<p class="muted">A collector runs once a day, reads the published EC2 price list for every tracked
region, validates it (minimum instance counts, price sanity checks, monthly-equals-hourly checks),
and only then publishes. If validation fails, nothing is published and the site keeps the previous
snapshot — the pipeline never guesses a price. Full detail on the
<a href="/methodology/">methodology page</a>, and the same data is available as a
<a href="/api/">free JSON feed</a>.</p>
{b.subscribe_form()}
"""
    b.add("/", f"AWS EC2 prices today: on-demand, spot and reserved ({human_date_short(b.today)})",
          "Daily AWS EC2 prices for on-demand, spot and reserved instances across "
          f"{b.meta.get('regions_tracked')} regions, plus a live comparison with cheaper cloud and VPS "
          "alternatives and a cloud cost savings calculator.",
          body, priority=1.0,
          jsonld=[{
              "@context": "https://schema.org", "@type": "WebSite",
              "name": "CloudCost Radar", "url": b.site.get("base_url"),
              "potentialAction": {
                  "@type": "SearchAction",
                  "target": b.url_for("/instances/") + "?q={search_term_string}",
                  "query-input": "required name=search_term_string",
              },
          }])


# --------------------------------------------------------------------------- instances

def build_instances_index(b: Builder) -> None:
    families = sorted({r["family"] for r in b.rows})
    vcpu_opts = "".join(f'<option>{n}</option>' for n in (0, 1, 2, 4, 8, 16, 32, 64, 96))
    fam_opts = "".join(f'<option value="{esc(f)}">{esc(f)}</option>' for f in families)

    initial = sorted(b.rows, key=lambda r: r["od_hour"])[:100]
    body_rows = []
    for row in initial:
        body_rows.append([
            f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
            f'<span class="num">{row["vcpu"]}</span>',
            f'<span class="num">{str(row["mem_gb"]).rstrip("0").rstrip(".")}</span>',
            f'<span class="num">{hourly(row["od_hour"])}</span>',
            f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>',
            f'<span class="num">{hourly(row["spot_hour"]) if row["spot_hour"] else "n/a"}</span>',
            f'<span class="num">{hourly(row["r1y_hour"]) if row["r1y_hour"] else "n/a"}</span>',
            '<span class="badge hot">GPU</span>' if row.get("gpu") else "",
        ])
    table = b.table(
        [("Instance", False, "type"), ("vCPU", True, "vcpu"), ("RAM GB", True, "mem"),
         ("On-demand /hr", True, "od"), ("On-demand /mo", True, "od"), ("Spot /hr", True, "spot"),
         ("1y reserved /hr", True, "r1"), ("Type", False, "gpu")],
        body_rows, table_id="instances-table", sort_key="od")

    body = f"""
<h1>All {len(b.rows):,} AWS EC2 instance prices</h1>
<p class="lede">Every instance type in US East (N. Virginia) with its published on-demand hourly and
monthly price, the current spot price, and the 1-year reserved rate. Prices collected
{esc(human_date(b.today))}. Sort by clicking a column header; filter by family, size or price.</p>
<div class="grid c2" style="margin:16px 0">
  <div class="card">
    <label for="instance-search">Search instance type</label>
    <input id="instance-search" type="search" placeholder="m7i.large, graviton, c6g…">
    <div class="grid c2">
      <div><label for="instance-family">Family</label>
        <select id="instance-family"><option value="">All families</option>{fam_opts}</select></div>
      <div><label for="instance-vcpu">Minimum vCPU</label>
        <select id="instance-vcpu">{vcpu_opts}</select></div>
      <div><label for="instance-max">Max on-demand $/hr</label>
        <input id="instance-max" type="number" step="0.01" min="0" placeholder="e.g. 0.20"></div>
      <div><label for="instance-gpu">Accelerators</label>
        <p class="small"><input type="checkbox" id="instance-gpu" style="width:auto"> GPU / accelerator only</p></div>
    </div>
    <div class="btnrow"><button class="btn ghost small" id="instance-reset" type="button">Reset filters</button></div>
  </div>
  <div class="card">
    <h3>What you are looking at</h3>
    <p class="small muted">On-demand is the list rate you pay with no commitment. Spot is the same
    instance at a discount that AWS can reclaim — the reclaim risk is shown on each instance page.
    Reserved is a 1- or 3-year commitment; the 1-year no-upfront rate is shown here.</p>
    <p class="small muted">Monthly figures are the hourly price × 730 hours, which is what a
    month-long instance actually costs. They are not AWS's own monthly rounding.</p>
    <div class="btnrow"><a class="btn ghost small" href="/cheapest/">Cheapest by size</a>
    <a class="btn ghost small" href="/gpu/">GPU only</a>
    <a class="btn ghost small" href="/spot/">Spot only</a></div>
  </div>
</div>
<p class="small muted" id="instance-count"></p>
{table}
<p class="small muted" id="instance-limit-note" style="display:none">Showing the first 300 matches.
Use the search box to narrow down.</p>
<h2>How to read EC2 instance names</h2>
<p class="muted">The first segment is the family (<span class="mono">m7i</span> = general purpose,
<span class="mono">c7i</span> = compute optimised, <span class="mono">r7i</span> = memory optimised,
<span class="mono">i4i</span> = storage optimised, <span class="mono">g6</span> = GPU,
<span class="mono">t3</span> = burstable). The letter after the number is the CPU vendor and
generation (<span class="mono">i</span> = Intel, <span class="mono">a</span> = AMD,
<span class="mono">g</span> = AWS Graviton ARM). The part after the dot is the size. Newer
generations usually cost the same or less than the generation they replace, which is why
re-checking the price list once a year is worth the ten minutes.</p>
"""
    b.add("/instances/", f"AWS EC2 instance prices: all {len(b.rows):,} types, on-demand and spot",
          f"Complete list of AWS EC2 instance types with on-demand, spot and reserved hourly prices, "
          f"updated {human_date(b.today)}. Filter by family, vCPU and price.",
          body, priority=0.95, breadcrumbs=[("Home", "/"), ("Instance prices", "/instances/")])


def build_instance_pages(b: Builder, mode: str = "all") -> int:
    count = 0
    for row in b.rows:
        if mode == "watchlist" and not (is_watchlisted(row["type"]) or row.get("gpu")):
            continue
        itype = row["type"]
        path = f"/instances/{itype}/"
        spec = f'{row["vcpu"]} vCPU, {str(row["mem_gb"]).rstrip("0").rstrip(".")} GB RAM'
        best_spot = row["spot_hour"]
        price_rows = [
            ["On-demand", hourly(row["od_hour"]), monthly_from_hour(row["od_hour"]),
             '<span class="muted small">no commitment</span>'],
        ]
        if best_spot:
            saving = (1 - best_spot / row["od_hour"]) * 100
            price_rows.append(["Spot", hourly(best_spot), monthly_from_hour(best_spot),
                               f'<span class="down">-{saving:.0f}%</span>'
                               f'<span class="muted small"> · reclaim risk '
                               f'{esc(row.get("spot_reclaim") or "unknown")}</span>'])
        if row["r1y_hour"]:
            price_rows.append(["1-year reserved (no upfront)", hourly(row["r1y_hour"]),
                               monthly_from_hour(row["r1y_hour"]),
                               f'<span class="down">-{(1-row["r1y_hour"]/row["od_hour"])*100:.0f}%</span>'])
        if row["r3y_hour"]:
            price_rows.append(["3-year reserved (no upfront)", hourly(row["r3y_hour"]),
                               monthly_from_hour(row["r3y_hour"]),
                               f'<span class="down">-{(1-row["r3y_hour"]/row["od_hour"])*100:.0f}%</span>'])
        if row["r1y_conv_hour"]:
            price_rows.append(["1-year convertible reserved", hourly(row["r1y_conv_hour"]),
                               monthly_from_hour(row["r1y_conv_hour"]), ""])
        price_table = b.table([("Purchase model", False), ("Per hour", True), ("Per month", True),
                               ("vs on-demand", False)], price_rows)

        region_rows = []
        for region in sorted(b.region_options(), key=lambda r: r["name"]):
            match = next((r for r in region["rows"] if r[0] == itype), None)
            if not match:
                continue
            region_rows.append([
                f'<a href="/regions/{esc(region["code"])}/">{esc(region["code"])}</a>',
                esc(region["name"]),
                f'<span class="num">{hourly(match[3])}</span>',
                f'<span class="num">{hourly(match[4]) if match[4] else "n/a"}</span>',
            ])
        region_table = b.table([("Region", False), ("Location", False), ("On-demand /hr", True),
                                ("Spot /hr", True)], region_rows)

        sim_rows = []
        for other in b.similar(row):
            sim_rows.append([
                f'<a href="/instances/{esc(other["type"])}/">{esc(other["type"])}</a>',
                f'<span class="num">{other["vcpu"]}</span>',
                f'<span class="num">{str(other["mem_gb"]).rstrip("0").rstrip(".")}</span>',
                f'<span class="num">{hourly(other["od_hour"])}</span>',
                f'<span class="num">{esc(pct(round((other["od_hour"]-row["od_hour"])/row["od_hour"]*100, 1)))}</span>',
            ])
        similar_table = b.table([("Instance", False), ("vCPU", True), ("RAM GB", True),
                                 ("On-demand /hr", True), ("vs this instance", True)], sim_rows)

        monthly = row["od_hour"] * 730
        alt_lines = []
        for prov in b.alternatives.get("providers", []):
            verified = [p for p in prov.get("plans", []) if p.get("price_status") == "verified"
                        and p["vcpu"] == row["vcpu"] and p["ram_gb"] >= row["mem_gb"]]
            if not verified:
                continue
            cheapest = min(verified, key=lambda p: p["price_usd_month"])
            saving = monthly - cheapest["price_usd_month"]
            if saving > 1:
                alt_lines.append(
                    f'<li><span>{esc(prov["name"])} <span class="muted small">'
                    f'{cheapest["vcpu"]} vCPU / {cheapest["ram_gb"]} GB</span></span>'
                    f'<span><strong>{usd(cheapest["price_usd_month"])}/mo</strong> '
                    f'<span class="down">-{usd(saving)}/mo</span></span></li>')
        alt_block = ""
        if alt_lines:
            alt_block = (f'<h2>Same specs, cheaper provider</h2><ul class="clean">{"".join(alt_lines)}</ul>'
                         f'<div class="btnrow"><a class="btn" href="/alternatives/">See every alternative</a></div>')

        faq = [
            (f"How much does {itype} cost per month?",
             f"At the published US East (N. Virginia) on-demand rate of {hourly(row['od_hour'])} per hour, "
             f"{itype} costs about {usd(monthly)} for a full 730-hour month, as read on "
             f"{human_date(b.today)}."
             + (f" The same instance on spot capacity was {hourly(best_spot)} per hour, about "
                f"{usd(best_spot*730)} per month, with a reclaim risk of "
                f"{row.get('spot_reclaim') or 'unknown'}." if best_spot else "")),
            (f"Is {itype} available in other regions?",
             f"{itype} appears in {len(region_rows)} of the regions this site tracks. Regional prices "
             "differ, so check the region table above before you pick a location."),
            (f"Should I use spot instead of on-demand for {itype}?",
             "Spot suits stateless and interruptible work — batch jobs, build fleets, queue consumers. "
             "It is a poor fit for a single-instance database or anything that cannot restart. The "
             "reclaim risk column above is AWS's own guidance for this instance type."),
        ]
        faq_html = "".join(f"<div class='faq'><h3>{esc(q)}</h3><p>{esc(a)}</p></div>" for q, a in faq)

        gpu_line = f"<p><span class='badge hot'>GPU</span> Accelerator: {esc(row['gpu'])}</p>" if row.get("gpu") else ""
        body = f"""
<h1>{esc(itype)} price: {hourly(row['od_hour'])}/hour on-demand, {hourly(best_spot)}/hour spot</h1>
<p class="lede">{esc(itype)} is a {esc(spec)} instance in the <span class="mono">{esc(row['family'])}</span>
family. Prices below were read from the published AWS price list on {esc(human_date(b.today))}, in
{esc(b.instances_doc.get('region_name','US East (N. Virginia)'))}.</p>
{gpu_line}
<div class="grid c4" style="margin:18px 0">
  {b.stat("On-demand", hourly(row['od_hour']), "per hour")}
  {b.stat("Monthly", monthly_from_hour(row['od_hour']), "730 hours")}
  {b.stat("Spot", hourly(best_spot), esc(row.get('spot_reclaim') or 'reclaim risk unknown'))}
  {b.stat("1y reserved", hourly(row['r1y_hour']), "no upfront")}
</div>
<h2>All purchase models</h2>
{price_table}
<h2>Specification</h2>
<div class="tablewrap"><table><tbody>
<tr><th>vCPU</th><td>{row['vcpu']}</td><th>Memory</th><td>{esc(str(row['mem_gb']).rstrip('0').rstrip('.'))} GB</td></tr>
<tr><th>Family</th><td><a href="/instances/">{esc(row['family'])}</a></td><th>Size</th><td>{esc(row['size'])}</td></tr>
<tr><th>Local storage</th><td>{esc(row.get('storage') or 'EBS only')}</td><th>Network</th><td>{esc(row.get('network') or 'n/a')}</td></tr>
</tbody></table></div>
{alt_block}
<h2>Price by region</h2>
{region_table}
<h2>Similar instance types</h2>
<p class="muted">Comparable vCPU and memory, sorted by how close their price is to {esc(itype)}.</p>
{similar_table}
<h2>Frequently asked</h2>
{faq_html}
<div class="btnrow"><a class="btn" href="/calculator/">Calculate monthly cost</a>
<a class="btn ghost" href="/instances/">All instance prices</a>
<a class="btn ghost" href="/spot/">Spot price tracker</a></div>
{b.subscribe_form("Track " + itype + " price changes")}
"""
        b.add(path,
              f"{itype} price: {hourly(row['od_hour'])}/hr on-demand, {hourly(best_spot)}/hr spot "
              f"({human_date_short(b.today)})",
              f"{itype} costs {hourly(row['od_hour'])} per hour ({monthly_from_hour(row['od_hour'])} per "
              f"month) on-demand in US East (N. Virginia)"
              + (f", and {hourly(best_spot)} per hour on spot" if best_spot else "")
              + f". {esc(spec)}. Verified {human_date(b.today)}.",
              body, priority=0.5,
              breadcrumbs=[("Home", "/"), ("Instance prices", "/instances/"), (itype, path)],
              jsonld=[
                  {"@context": "https://schema.org", "@type": "Product",
                   "name": f"AWS EC2 {itype}",
                   "description": f"Amazon EC2 {itype} instance: {spec}.",
                   "offers": {"@type": "Offer", "price": f"{row['od_hour']:.4f}",
                              "priceCurrency": "USD",
                              "description": "On-demand list price per hour in US East (N. Virginia)",
                              "availability": "https://schema.org/InStock",
                              "url": b.url_for(path)}},
                  {"@context": "https://schema.org", "@type": "FAQPage",
                   "mainEntity": [
                       {"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a}}
                       for q, a in faq]},
              ])
        count += 1
    return count


# --------------------------------------------------------------------------- spot

def build_spot(b: Builder) -> None:
    today_path = DATA / "changes" / f"{b.today}.json"
    changes = json.loads(today_path.read_text(encoding="utf-8")) if today_path.exists() else {}
    movers_down = [m for m in (changes.get("spot_movers") or []) if m["pct"] < 0][:20]
    movers_up = [m for m in (changes.get("spot_movers") or []) if m["pct"] > 0][:10]

    history_files = b.spot_history_days()
    history = {}
    for path in history_files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        history[path.stem] = doc.get("regions", {})
    days = sorted(history)
    oldest = days[0] if days else None

    def week_change(region: str, itype: str):
        if not days:
            return None
        region_hist = [(d, history[d].get(region, {}).get(itype)) for d in days]
        region_hist = [(d, v) for d, v in region_hist if v is not None]
        if len(region_hist) < 2:
            return None
        first = region_hist[0][1]
        last = region_hist[-1][1]
        if not first:
            return None
        return round((last - first) / first * 100, 1)

    watch_rows = []
    today_spot = history.get(b.today, {}).get(b.instances_doc.get("region", "us-east-1"), {})
    lookup = {r["type"]: r for r in b.rows}
    for itype in sorted(today_spot):
        row = lookup.get(itype)
        if not row:
            continue
        change = week_change(b.instances_doc.get("region", "us-east-1"), itype)
        watch_rows.append([
            f'<a href="/instances/{esc(itype)}/">{esc(itype)}</a>',
            f'<span class="num">{hourly(row["od_hour"])}</span>',
            f'<span class="num">{hourly(today_spot[itype])}</span>',
            f'<span class="num down">-{(1-today_spot[itype]/row["od_hour"])*100:.0f}%</span>',
            f'<span class="num">{esc(pct(change)) if change is not None else "–"}</span>',
            f'<span class="muted small">{esc(row.get("spot_reclaim") or "unknown")}</span>',
        ])
    watch_table = b.table([("Instance", False), ("On-demand /hr", True), ("Spot /hr", True),
                           ("Spot discount", True), (f"Change since {human_date_short(oldest) if oldest else 'baseline'}", True),
                           ("Reclaim risk", False)], watch_rows[:200])

    def mover_table(items, positive=False):
        rows = []
        for m in items:
            rows.append([
                f'<a href="/instances/{esc(m["type"])}/">{esc(m["type"])}</a>',
                f'<span class="muted small">{esc(m["region"])}</span>',
                f'<span class="num">{hourly(m["from"])}</span>',
                f'<span class="num">{hourly(m["to"])}</span>',
                f'<span class="{"up" if positive else "down"}">{esc(pct(m["pct"]))}</span>',
            ])
        return b.table([("Instance", False), ("Region", False), ("Previous", True), ("Now", True),
                        ("Change", True)], rows) if rows else '<p class="muted">No moves recorded yet.</p>'

    cheapest_spot = sorted([r for r in b.rows if r["spot_hour"]], key=lambda r: r["spot_hour"])[:10]
    cheap_rows = []
    for row in cheapest_spot:
        cheap_rows.append([
            f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
            f'<span class="num">{row["vcpu"]}</span>',
            f'<span class="num">{str(row["mem_gb"]).rstrip("0").rstrip(".")}</span>',
            f'<span class="num">{hourly(row["spot_hour"])}</span>',
            f'<span class="num">{monthly_from_hour(row["spot_hour"])}</span>',
            f'<span class="muted small">{esc(row.get("spot_reclaim") or "unknown")}</span>',
        ])
    cheap_table = b.table([("Instance", False), ("vCPU", True), ("RAM GB", True),
                           ("Spot /hr", True), ("Spot /mo", True), ("Reclaim risk", False)], cheap_rows)

    body = f"""
<h1>AWS spot price tracker — {esc(human_date(b.today))}</h1>
<p class="lede">Spot instances are unused EC2 capacity sold at a discount, with AWS free to reclaim
them at two minutes' notice. CloudCost Radar records {len(watch_rows):,} spot prices in
{b.instances_doc.get('region_name','US East (N. Virginia)')} every day and keeps the history, so you
can see whether today's price is actually a good deal or just normal noise.</p>
<div class="grid c4" style="margin:18px 0">
  {b.stat("Spot prices today", f"{len(watch_rows):,}", "in the primary region")}
  {b.stat("Drops recorded", str(len(movers_down)), "moves of 1% or more")}
  {b.stat("Increases recorded", str(len(movers_up)), "moves of 1% or more")}
  {b.stat("History starts", esc(human_date_short(oldest)) if oldest else "today", f"{len(days)} daily snapshots")}
</div>
<h2>Biggest spot price drops</h2>
{mover_table(movers_down)}
<h2>Biggest spot price increases</h2>
{mover_table(movers_up, positive=True)}
<h2>Cheapest spot capacity today</h2>
{cheap_table}
<h2>Spot versus on-demand, instance by instance</h2>
<p class="muted">The discount column is what you save against the same instance on-demand. The change
column compares today's spot price with the earliest snapshot in this site's history — a large
discount today may simply be the normal level for that instance.</p>
{watch_table}
<h2>Using spot without losing your workload</h2>
<p class="muted">The useful pattern is to make the tricky part stateless: keep state in a database or
object store, run the compute on spot, and let an autoscaling group or a queue replace instances that
get reclaimed. Instance types with a low reclaim risk are the safe ones to start with; those with a
high risk belong in batch pipelines that can tolerate restarts. If a workload must run continuously
and cannot be restarted, reserved capacity or a cheaper provider is usually the better answer —
see <a href="/alternatives/">the alternatives comparison</a>.</p>
{b.ad_slot('home_bottom')}
{b.subscribe_form("Get spot price alerts")}
"""
    b.add("/spot/", f"AWS spot prices today: {len(movers_down)} drops recorded ({human_date_short(b.today)})",
          "Daily AWS EC2 spot price tracker: biggest drops and increases, cheapest spot capacity, and "
          "spot-versus-on-demand discounts for popular instance types, with permanent price history.",
          body, priority=0.9, breadcrumbs=[("Home", "/"), ("Spot prices", "/spot/")])


# --------------------------------------------------------------------------- regions

def build_regions(b: Builder) -> None:
    regions = sorted(b.region_options(), key=lambda r: r["name"])
    rows = []
    for region in regions:
        cheap = sorted(region["rows"], key=lambda r: r[3])[:1]
        cheap_two = sorted([r for r in region["rows"] if r[1] == 2], key=lambda r: r[3])[:1]
        spot = [r[4] for r in region["rows"] if r[4]]
        rows.append([
            f'<a href="/regions/{esc(region["code"])}/">{esc(region["code"])}</a>',
            esc(region["name"]),
            f'<span class="num">{len(region["rows"]):,}</span>',
            f'<span class="num">{esc(cheap[0][0]) if cheap else "n/a"}</span>',
            f'<span class="num">{hourly(cheap[0][3]) if cheap else "n/a"}</span>',
            f'<span class="num">{esc(cheap_two[0][0]) if cheap_two else "n/a"}</span>',
            f'<span class="num">{hourly(cheap_two[0][3]) if cheap_two else "n/a"}</span>',
            f'<span class="num">{len(spot):,}</span>',
        ])
    table = b.table([("Region", False), ("Location", False), ("Types", True),
                     ("Cheapest", False), ("$ /hr", True), ("Cheapest 2 vCPU", False),
                     ("$ /hr", True), ("Spot prices", True)], rows)

    body = f"""
<h1>AWS prices by region</h1>
<p class="lede">The same instance type costs different amounts in different AWS regions, and region
choice is also a latency and compliance decision. This table shows how many instance types each
region sells, the cheapest instance available there today, and the cheapest 2 vCPU option —
all read from the published price list on {esc(human_date(b.today))}.</p>
{table}
<h2>Choosing a region</h2>
<p class="muted">Three things decide it: where your users are (latency), where your data is legally
allowed to sit (residency), and price. Price differences between regions for identical hardware are
usually small, so it rarely pays to move a workload purely to save a few percent — but it does pay
to check whether a workload is running in an expensive region out of habit. Regions with fewer
instance types, such as Cape Town, Osaka or Zurich, may simply not offer the newest families.</p>
<div class="btnrow"><a class="btn" href="/instances/">All instance prices</a>
<a class="btn ghost" href="/calculator/">Savings calculator</a></div>
{b.subscribe_form()}
"""
    b.add("/regions/", f"AWS prices by region: cheapest instances in {len(regions)} regions",
          "Compare AWS EC2 pricing across all tracked regions: instance counts, cheapest available "
          "instance, cheapest 2 vCPU option and spot availability, updated daily.",
          body, priority=0.8, breadcrumbs=[("Home", "/"), ("Regions", "/regions/")])

    for region in regions:
        code = region["code"]
        rows_sorted = sorted(region["rows"], key=lambda r: r[3])
        cheap_rows = []
        for r in rows_sorted[:25]:
            cheap_rows.append([
                f'<a href="/instances/{esc(r[0])}/">{esc(r[0])}</a>',
                f'<span class="num">{r[1]}</span>',
                f'<span class="num">{str(r[2]).rstrip("0").rstrip(".")}</span>',
                f'<span class="num">{hourly(r[3])}</span>',
                f'<span class="num">{monthly_from_hour(r[3])}</span>',
                f'<span class="num">{hourly(r[4]) if r[4] else "n/a"}</span>',
            ])
        table = b.table([("Instance", False), ("vCPU", True), ("RAM GB", True),
                         ("On-demand /hr", True), ("On-demand /mo", True), ("Spot /hr", True)],
                        cheap_rows)
        per_vcpu = []
        for vcpu in (1, 2, 4, 8, 16):
            pool = sorted([r for r in region["rows"] if r[1] == vcpu], key=lambda r: r[3])
            if pool:
                per_vcpu.append([
                    esc(f"{vcpu} vCPU"),
                    f'<a href="/instances/{esc(pool[0][0])}/">{esc(pool[0][0])}</a>',
                    f'<span class="num">{str(pool[0][2]).rstrip("0").rstrip(".")}</span>',
                    f'<span class="num">{hourly(pool[0][3])}</span>',
                    f'<span class="num">{monthly_from_hour(pool[0][3])}</span>',
                ])
        per_vcpu_table = b.table([("Size class", False), ("Cheapest instance", False), ("RAM GB", True),
                                  ("On-demand /hr", True), ("On-demand /mo", True)], per_vcpu)
        spot_count = len([r for r in region["rows"] if r[4]])

        body = f"""
<h1>AWS pricing in {esc(region['name'])} ({esc(code)})</h1>
<p class="lede">{len(region['rows']):,} instance types are sold in <span class="mono">{esc(code)}</span>,
{spot_count:,} of them with a current spot price. The cheapest instance today is
{esc(rows_sorted[0][0])} at {hourly(rows_sorted[0][3])} per hour. Prices read
{esc(human_date(b.today))}.</p>
<h2>Cheapest instance by size class in {esc(code)}</h2>
{per_vcpu_table}
<h2>25 cheapest instances in {esc(code)}</h2>
{table}
<h2>Other regions</h2>
<p class="muted">Compare with <a href="/regions/">every tracked region</a>, or look up a specific
instance type on its own page to see how its price changes by location.</p>
<div class="btnrow"><a class="btn ghost" href="/regions/">All regions</a>
<a class="btn ghost" href="/instances/">All instance prices</a></div>
"""
        b.add(f"/regions/{code}/", f"AWS prices in {region['name']} ({code}) — cheapest instances today",
              f"AWS EC2 pricing for {region['name']} ({code}): cheapest instance by size class, the 25 "
              f"cheapest instance types today and spot availability, updated {human_date(b.today)}.",
              body, priority=0.65,
              breadcrumbs=[("Home", "/"), ("Regions", "/regions/"), (code, f"/regions/{code}/")],
              jsonld=[{"@context": "https://schema.org", "@type": "Dataset",
                       "name": f"AWS EC2 prices in {region['name']} ({code})",
                       "description": f"Daily AWS EC2 on-demand and spot prices for {code}.",
                       "temporalCoverage": b.today, "license": "https://creativecommons.org/licenses/by/4.0/",
                       "creator": {"@type": "Organization", "name": "CloudCost Radar"}}])


# --------------------------------------------------------------------------- cheapest / gpu

def build_cheapest(b: Builder) -> None:
    cards = []
    for vcpu, ram in SPEC_PAGES:
        best = b.cheapest(vcpu=vcpu, min_mem=ram, limit=1)
        if not best:
            continue
        row = best[0]
        label = f"{vcpu} vCPU / {ram} GB"
        cards.append([
            f'<a href="/cheapest/{vcpu}-vcpu-{ram}gb/">{esc(label)}</a>',
            f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
            f'<span class="num">{hourly(row["od_hour"])}</span>',
            f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>',
            f'<span class="num">{hourly(row["spot_hour"]) if row["spot_hour"] else "n/a"}</span>',
        ])
    table = b.table([("Spec", False), ("Cheapest instance", False), ("On-demand /hr", True),
                     ("On-demand /mo", True), ("Spot /hr", True)], cards)

    under10 = sorted([r for r in b.rows if r["od_hour"] * 730 <= 10], key=lambda r: r["od_hour"])[:20]
    under_rows = []
    for row in under10:
        under_rows.append([
            f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
            f'<span class="num">{row["vcpu"]}</span>',
            f'<span class="num">{str(row["mem_gb"]).rstrip("0").rstrip(".")}</span>',
            f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>',
            f'<span class="num">{hourly(row["od_hour"])}</span>',
        ])
    under_table = b.table([("Instance", False), ("vCPU", True), ("RAM GB", True),
                           ("Monthly", True), ("Per hour", True)], under_rows)

    body = f"""
<h1>Cheapest AWS instance for every common size</h1>
<p class="lede">If you know what you need — 4 vCPU and 16 GB, say — this is the cheapest way to buy
it on AWS today, and what it would cost on spot or on a cheaper provider. Prices read
{esc(human_date(b.today))} in US East (N. Virginia).</p>
{table}
<h2>AWS instances under $10 per month</h2>
<p class="muted">The bottom of the AWS price list. These are fine for cron jobs, tiny APIs, proxies
and monitoring agents — not for anything that needs real memory headroom.</p>
{under_table}
<h2>How to use this</h2>
<p class="muted">Pick the size class closest to your actual usage, not the size class you guessed six
months ago. Most oversized bills are the result of a workload that was provisioned for a launch
spike and never resized. If the monthly number still looks wrong for what the workload does, the
<a href="/alternatives/">alternatives comparison</a> shows what the same specs cost elsewhere, and
the <a href="/calculator/">calculator</a> quantifies the switch.</p>
<div class="btnrow"><a class="btn" href="/calculator/">Calculate your savings</a>
<a class="btn ghost" href="/gpu/">Cheapest GPU instances</a></div>
"""
    b.add("/cheapest/", "Cheapest AWS instance by size: 1-16 vCPU, on-demand and spot prices",
          "The cheapest AWS EC2 instance for every common size class, plus every instance under $10 a "
          "month, with on-demand, spot and monthly costs, updated daily.",
          body, priority=0.85, breadcrumbs=[("Home", "/"), ("Cheapest by size", "/cheapest/")])

    for vcpu, ram in SPEC_PAGES:
        pool = sorted([r for r in b.rows if r["vcpu"] == vcpu and r["mem_gb"] >= ram],
                      key=lambda r: r["od_hour"])[:15]
        if not pool:
            continue
        rows = []
        for row in pool:
            rows.append([
                f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
                f'<span class="num">{str(row["mem_gb"]).rstrip("0").rstrip(".")}</span>',
                f'<span class="num">{hourly(row["od_hour"])}</span>',
                f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>',
                f'<span class="num">{hourly(row["spot_hour"]) if row["spot_hour"] else "n/a"}</span>',
                f'<span class="num">{hourly(row["r1y_hour"]) if row["r1y_hour"] else "n/a"}</span>',
            ])
        table = b.table([("Instance", False), ("RAM GB", True), ("On-demand /hr", True),
                         ("On-demand /mo", True), ("Spot /hr", True), ("1y reserved /hr", True)], rows)
        best = pool[0]
        alt_rows = []
        for prov in b.alternatives.get("providers", []):
            for plan in prov.get("plans", []):
                if plan.get("price_status") != "verified":
                    continue
                if plan["vcpu"] < vcpu or plan["ram_gb"] < ram:
                    continue
                alt_rows.append([
                    esc(prov["name"]),
                    f'<span class="num">{plan["vcpu"]}</span>',
                    f'<span class="num">{plan["ram_gb"]}</span>',
                    f'<span class="num">{usd(plan["price_usd_month"])}</span>',
                    f'<span class="down">-{usd(best["od_hour"]*730 - plan["price_usd_month"])}</span>',
                    b.provider_link(prov["id"], prov["verify_url"], "Pricing"),
                ])
        alt_table = (b.table([("Provider", False), ("vCPU", True), ("RAM GB", True), ("Monthly", True),
                              ("vs cheapest AWS", True), ("", False)], alt_rows)
                     if alt_rows else
                     '<p class="muted">No provider price for this size class has been machine-verified '
                     'yet, so this page deliberately shows none. See the '
                     '<a href="/alternatives/">alternatives page</a> for live pricing links.</p>')
        body = f"""
<h1>Cheapest {vcpu} vCPU {ram} GB instance on AWS</h1>
<p class="lede">The cheapest way to buy {vcpu} vCPU with at least {ram} GB of RAM on AWS today is
<strong>{esc(best['type'])}</strong> at {hourly(best['od_hour'])} per hour
({monthly_from_hour(best['od_hour'])} per month for 730 hours). Prices read
{esc(human_date(b.today))} in US East (N. Virginia).</p>
<h2>All {vcpu} vCPU options with {ram} GB or more</h2>
{table}
<h2>The same specs outside AWS</h2>
{alt_table}
<h2>What to watch before you pick the cheapest</h2>
<p class="muted">Cheapest by list price is not always cheapest by bill. Three things move the number:
egress charges (AWS bills data transfer out, most VPS providers include an allowance), storage and
IOPS (check whether the plan includes NVMe), and CPU credit behaviour on burstable families like
<span class="mono">t3</span> and <span class="mono">t4g</span>, which throttle when you exhaust
credits rather than letting you run faster. If your workload is steady rather than spiky, a
non-burstable family is usually the honest choice — and often cheaper per unit of delivered work.</p>
<div class="btnrow"><a class="btn" href="/instances/">All instance prices</a>
<a class="btn ghost" href="/alternatives/">Alternatives</a></div>
"""
        b.add(f"/cheapest/{vcpu}-vcpu-{ram}gb/",
              f"Cheapest {vcpu} vCPU {ram} GB instance on AWS ({human_date_short(b.today)})",
              f"The cheapest AWS EC2 instances with {vcpu} vCPU and at least {ram} GB RAM, with "
              f"on-demand, spot and reserved prices, plus verified cheaper alternatives.",
              body, priority=0.7,
              breadcrumbs=[("Home", "/"), ("Cheapest by size", "/cheapest/"),
                           (f"{vcpu} vCPU / {ram} GB", f"/cheapest/{vcpu}-vcpu-{ram}gb/")])


def build_gpu(b: Builder) -> None:
    gpu = sorted([r for r in b.rows if r.get("gpu")], key=lambda r: r["od_hour"])
    rows = []
    for row in gpu:
        rows.append([
            f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>',
            esc(row["gpu"]),
            f'<span class="num">{row["vcpu"]}</span>',
            f'<span class="num">{str(row["mem_gb"]).rstrip("0").rstrip(".")}</span>',
            f'<span class="num">{hourly(row["od_hour"])}</span>',
            f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>',
            f'<span class="num">{hourly(row["spot_hour"]) if row["spot_hour"] else "n/a"}</span>',
        ])
    table = b.table([("Instance", False), ("Accelerator", False), ("vCPU", True), ("RAM GB", True),
                     ("On-demand /hr", True), ("On-demand /mo", True), ("Spot /hr", True)], rows)

    body = f"""
<h1>AWS GPU instance prices — all {len(gpu)} accelerator types</h1>
<p class="lede">GPU instances are the most expensive line on most AWS bills, and the ones people
over-provision most often. This is every accelerator instance AWS sells in US East (N. Virginia)
with today's on-demand and spot prices, read {esc(human_date(b.today))}.</p>
{table}
<h2>Four rules that cut GPU bills</h2>
<p class="muted"><strong>1. Spot first for training.</strong> Training jobs that checkpoint can run on
spot at a large discount; the reclaim risk column on each instance page tells you how aggressive
AWS is with that particular type. <strong>2. Rent by the hour elsewhere when utilisation is low.</strong>
If the GPU sits idle more than half the month, a per-hour GPU cloud is usually cheaper than any
committed AWS rate — see the providers listed on the
<a href="/alternatives/">alternatives page</a>. <strong>3. Match the accelerator to the job.</strong>
Inference at modest scale rarely needs the biggest card; a smaller instance with a modern
accelerator often finishes the same request cheaper. <strong>4. Check the network.</strong> Training
across nodes is bounded by interconnect, and the cheapest instance is not the fastest one.</p>
<div class="btnrow"><a class="btn" href="/calculator/">Compare purchase models</a>
<a class="btn ghost" href="/instances/">All instance prices</a></div>
{b.subscribe_form("GPU price alerts")}
"""
    b.add("/gpu/", f"AWS GPU instance prices: {len(gpu)} accelerator types, updated daily",
          "Every AWS GPU and accelerator instance type with on-demand, spot and monthly prices, "
          "updated daily, plus practical guidance on cutting GPU bills.",
          body, priority=0.8, breadcrumbs=[("Home", "/"), ("GPU instances", "/gpu/")])


# --------------------------------------------------------------------------- alternatives

def build_alternatives(b: Builder) -> None:
    providers = b.alternatives.get("providers", [])
    cards = []
    for prov in providers:
        plans = prov.get("plans", [])
        plan_rows = []
        for plan in plans:
            if plan.get("price_status") == "verified" and plan.get("price_usd_month") is not None:
                aws_equiv = b.cheapest(vcpu=plan["vcpu"], min_mem=plan["ram_gb"], limit=1)
                compare = ""
                if aws_equiv:
                    aws_month = aws_equiv[0]["od_hour"] * 730
                    diff = aws_month - plan["price_usd_month"]
                    compare = (f'<span class="down">-{usd(diff)}/mo</span>' if diff > 0
                               else f'<span class="up">+{usd(abs(diff))}/mo</span>')
                price = f'<strong>{usd(plan["price_usd_month"])}</strong>'
            else:
                compare = '<span class="muted small">live price</span>'
                price = '<span class="muted">see provider</span>'
            plan_rows.append([
                esc(plan["id"]),
                f'<span class="num">{plan["vcpu"] or "–"}</span>',
                f'<span class="num">{plan["ram_gb"] or "–"}</span>',
                f'<span class="num">{plan["disk_gb"] or "–"}</span>',
                price, compare,
            ])
        verified_count = len([p for p in plans if p.get("price_status") == "verified"])
        note = (f'{verified_count} of {len(plans)} listed sizes have a price verified by this site'
                if verified_count else
                'This provider renders prices in JavaScript, so no number is shown here until it can be '
                'read reliably')
        cards.append(f"""
<div class="card">
  <h2 style="margin-top:0">{esc(prov['name'])}</h2>
  <p class="small muted">{esc(prov.get('notes',''))}</p>
  <p class="small">{esc(note)} · <span class="muted">source: <a href="{esc(prov['verify_url'])}" rel="noopener" target="_blank">published pricing page</a></span></p>
  {b.table([("Plan", False), ("vCPU", True), ("RAM GB", True), ("Disk GB", True), ("Monthly", True),
            ("vs cheapest AWS", True)], plan_rows)}
  <div class="btnrow">{b.provider_link(prov['id'], prov['verify_url'], 'Check ' + prov['name'] + ' pricing', small=False)}</div>
</div>""")

    body = f"""
<h1>Cheaper cloud and VPS alternatives to AWS EC2</h1>
<p class="lede">For workloads that run all month — web apps, APIs, queues, small databases — the
managed VPS market sells the same vCPU and RAM for a fraction of on-demand EC2 prices. This page
lists what each provider charges, shows how it compares with the cheapest AWS instance of the same
spec today, and is explicit about which numbers this site has actually verified.</p>
<div class="notice">This page is the one commercial part of CloudCost Radar: outbound provider links
may be referral links. Ranking and the numbers above are computed from published prices, and a
provider cannot pay to appear higher. Details in the
<a href="/affiliate-disclosure/">affiliate disclosure</a>.</div>
{''.join(cards)}
<h2>What changes when you leave AWS</h2>
<p class="muted">The price is only half the decision. Leaving AWS means giving up the managed
services you already use (RDS, S3, IAM, CloudWatch, ALB), the shared VPC story, and the ecosystem
your engineers know. It also means you stop paying AWS prices for egress, which is where a lot of
surprise bills come from — most VPS providers include a fixed transfer allowance. The honest
framing: move the boring, self-contained compute (workers, cron, staging, internal tools, simple
web apps) and keep the parts that are genuinely hard to run yourself. That usually removes the
majority of the waste without a migration project.</p>
<h2>How to size the move</h2>
<p class="muted">Pull the actual utilisation numbers rather than the provisioned numbers. A
4-vCPU instance running at 12% CPU is a 1-vCPU workload with a confidence problem. Match RAM to peak
working set, not to what a previous team guessed. The <a href="/calculator/">calculator</a> turns the
current AWS price into a monthly and annual figure you can put next to a provider quote.</p>
<div class="btnrow"><a class="btn" href="/calculator/">Open the calculator</a>
<a class="btn ghost" href="/compare/aws-ec2-vs-digitalocean/">AWS vs DigitalOcean</a>
<a class="btn ghost" href="/compare/aws-ec2-vs-hetzner/">AWS vs Hetzner</a></div>
{b.subscribe_form()}
"""
    b.add("/alternatives/", "Cheaper AWS alternatives: cloud and VPS prices compared daily",
          "Cloud and VPS providers that cost less than AWS EC2 for the same vCPU and RAM, with "
          "verified published prices, a candid look at what you give up and how to size a move.",
          body, priority=0.9,
          breadcrumbs=[("Home", "/"), ("Alternatives", "/alternatives/")],
          jsonld=[{"@context": "https://schema.org", "@type": "ItemList",
                   "name": "Cloud and VPS alternatives to AWS EC2",
                   "itemListElement": [
                       {"@type": "ListItem", "position": i + 1, "name": p["name"],
                        "url": p["verify_url"]} for i, p in enumerate(providers)]}])


def build_compare(b: Builder) -> None:
    for slug_name, title in COMPARE_PAGES:
        parts = slug_name.split("-vs-")
        left_key = parts[0]
        right_key = parts[1].replace("ec2-", "")
        prov_right = next((p for p in b.alternatives.get("providers", [])
                           if p["id"] in right_key or right_key in p["id"]), None)
        tiers = []
        for vcpu, ram in ((2, 4), (4, 8), (8, 16), (16, 32)):
            aws = b.cheapest(vcpu=vcpu, min_mem=ram, limit=1)
            if not aws:
                continue
            row = aws[0]
            cells = [esc(f"{vcpu} vCPU / {ram} GB")]
            if left_key.startswith("aws"):
                cells.append(f'<a href="/instances/{esc(row["type"])}/">{esc(row["type"])}</a>')
                cells.append(f'<span class="num">{hourly(row["od_hour"])}</span>')
                cells.append(f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>')
                cells.append(f'<span class="num">{hourly(row["spot_hour"]) if row["spot_hour"] else "n/a"}</span>')
                if prov_right:
                    plans = [p for p in prov_right.get("plans", [])
                             if p.get("price_status") == "verified" and p["vcpu"] >= vcpu
                             and p["ram_gb"] >= ram]
                    if plans:
                        plan = min(plans, key=lambda p: p["price_usd_month"])
                        diff = row["od_hour"] * 730 - plan["price_usd_month"]
                        cells.append(f'<span class="num">{usd(plan["price_usd_month"])}</span>')
                        cells.append(f'<span class="{"down" if diff > 0 else "up"}">{usd(abs(diff))} '
                                     f'{"cheaper" if diff > 0 else "dearer"}</span>')
                    else:
                        cells.append('<span class="muted small">check provider</span>')
                        cells.append("")
            else:
                cells.append(f'<span class="num">{hourly(row["od_hour"])}</span>')
                cells.append(f'<span class="num">{monthly_from_hour(row["od_hour"])}</span>')
            tiers.append(cells)

        headers = [("Size", False)]
        if left_key.startswith("aws"):
            headers += [("AWS instance", False), ("AWS /hr", True), ("AWS /mo", True), ("AWS spot /hr", True)]
            if prov_right:
                headers += [(f"{prov_right['name']} /mo", True), ("Difference", False)]
        else:
            headers += [("AWS /hr", True), ("AWS /mo", True)]

        editorial = {
            "aws-ec2-vs-digitalocean": (
                "DigitalOcean is the closest thing to a drop-in replacement for simple EC2 workloads: "
                "SSD-backed droplets, hourly billing, predictable bandwidth allowances and a much "
                "smaller set of moving parts. What it does not have is the long tail of managed "
                "services — no equivalent depth in IAM, VPC peering or enterprise support. It is the "
                "right move for a self-contained app server, and the wrong move for a workload held "
                "together by eight AWS services."),
            "aws-ec2-vs-vultr": (
                "Vultr competes on price and region count rather than on a managed-service catalogue. "
                "Useful when you want many locations close to users and you are comfortable running "
                "your own stack on top of plain VMs."),
            "aws-ec2-vs-hetzner": (
                "Hetzner is the price outlier: European and US locations with strong hardware per "
                "euro, and a famously simple product line. The trade-offs are real — support is "
                "ticket-based rather than enterprise-grade, and you should read the terms if you "
                "have strict compliance requirements. For internal tools, CI runners, staging and "
                "small production apps it is often the cheapest credible option."),
            "aws-ec2-vs-linode": (
                "Linode (now part of Akamai) sits between the bare VPS providers and the cloud "
                "platforms: simple pricing, decent network, and a smaller ecosystem than AWS."),
            "aws-ec2-vs-lightsail": (
                "Lightsail is AWS selling you a fixed-price VPS with the AWS console. It makes sense "
                "when you must stay inside AWS for compliance or billing reasons — it is usually "
                "cheaper than the same spec on EC2 on-demand, and you keep AWS support, IAM and "
                "billing in one place."),
            "hetzner-vs-digitalocean": (
                "Both sell plain VMs. Hetzner generally wins on raw price per vCPU and RAM in the "
                "locations it covers; DigitalOcean wins on documentation, ecosystem, add-on services "
                "and regional spread. Pick by what you are optimising for, and check both against "
                "actual egress volume — the transfer allowances differ."),
        }.get(slug_name, "")

        body = f"""
<h1>{esc(title)}: what the same spec costs today</h1>
<p class="lede">Compared at the sizes people actually buy, using published prices read
{esc(human_date(b.today))}. AWS figures are on-demand list prices for US East (N. Virginia) with the
current spot rate alongside; a blank or "check provider" cell means this site has not verified a
machine-readable price for that provider, and it will not guess one.</p>
<h2>Price by size</h2>
{b.table(headers, tiers)}
<h2>The decision, honestly</h2>
<p class="muted">{esc(editorial)}</p>
<h2>What to check before switching</h2>
<p class="muted">Egress and storage pricing, snapshot and backup costs, whether the provider bills
hourly or monthly (hourly billing matters if you scale up and down), the contract length, and what
their support response time actually is on the plan you are buying. Then run the numbers for one
workload — not the whole estate — using the <a href="/calculator/">calculator</a>, and migrate that
one. A single migrated workload tells you more than a comparison table.</p>
<div class="btnrow"><a class="btn" href="/alternatives/">All alternatives</a>
<a class="btn ghost" href="/instances/">AWS instance prices</a></div>
"""
        b.add(f"/compare/{slug_name}/", f"{title} — price comparison ({human_date_short(b.today)})",
              f"{title}: side-by-side monthly pricing at common sizes, with AWS on-demand and spot "
              f"rates and verified provider prices, updated {human_date(b.today)}.",
              body, priority=0.7,
              breadcrumbs=[("Home", "/"), ("Alternatives", "/alternatives/"),
                           (title, f"/compare/{slug_name}/")])


# --------------------------------------------------------------------------- tools / meta pages

def build_calculator(b: Builder) -> None:
    body = f"""
<h1>Cloud cost calculator: on-demand, spot, reserved or another provider</h1>
<p class="lede">Enter the size of one instance and how many you run. The calculator finds the cheapest
matching AWS instance from today's published price list ({esc(human_date(b.today))}) and prices the
same workload across every purchase model — on-demand, spot, 1-year and 3-year reserved.</p>
<section class="card" id="calculator">
  <div class="grid c4">
    <div><label for="calc-vcpu">vCPU per instance</label>
      <select id="calc-vcpu"><option>1</option><option selected>2</option><option>4</option>
      <option>8</option><option>16</option><option>32</option><option>64</option></select></div>
    <div><label for="calc-ram">Minimum RAM (GB)</label>
      <select id="calc-ram"><option>1</option><option>2</option><option selected>4</option>
      <option>8</option><option>16</option><option>32</option><option>64</option>
      <option>128</option></select></div>
    <div><label for="calc-count">How many instances</label>
      <select id="calc-count"><option selected>1</option><option>2</option><option>3</option>
      <option>5</option><option>10</option><option>20</option><option>50</option></select></div>
  </div>
  <div id="calc-out" class="calc-out" style="margin-top:16px"></div>
</section>
<h2>Which purchase model actually fits</h2>
<p class="muted"><strong>On-demand</strong> is for workloads you do not know the shape of yet, or that
run for days rather than months. <strong>Spot</strong> is for anything that can be restarted: batch
jobs, build fleets, queue workers, stateless web tiers behind a load balancer. The discount is real
but so is the reclaim risk. <strong>Reserved</strong> only beats on-demand when the instance is
genuinely running most hours of the commitment period — buying a 1-year reservation for something you
might retire in four months is a way to lose money. If a workload is steady and boring, do not stop at
reserved: check what the same spec costs on a provider built for steady, boring workloads, which is
usually less than any AWS discount.</p>
<h2>What the calculator leaves out</h2>
<p class="muted">Real bills include storage, snapshots, load balancers, NAT gateways, data transfer
and managed databases. The calculator prices compute only, because compute is the part you can
compare like for like. Treat the answer as the compute component of the bill, then add the parts
that do not scale with your instance size.</p>
<div class="btnrow"><a class="btn" href="/alternatives/">Compare providers</a>
<a class="btn ghost" href="/cheapest/">Cheapest by size class</a></div>
{b.subscribe_form()}
"""
    b.add("/calculator/", "Cloud cost calculator: on-demand vs spot vs reserved vs alternatives",
          "Work out what a workload really costs on AWS across on-demand, spot and reserved pricing, "
          "using today's published prices, and see the monthly and annual saving available.",
          body, priority=0.75,
          breadcrumbs=[("Home", "/"), ("Calculator", "/calculator/")])


def build_changes(b: Builder) -> None:
    days = b.changes_days()
    blocks = []
    for path in days[:60]:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        od = doc.get("on_demand_changes") or []
        new = doc.get("new_instance_types") or []
        retired = doc.get("retired_instance_types") or []
        movers = doc.get("spot_movers") or []
        if not (od or new or retired or movers):
            continue
        rows = []
        for c in od[:20]:
            rows.append([
                f'<a href="/instances/{esc(c["type"])}/">{esc(c["type"])}</a>',
                '<span class="badge">on-demand</span>',
                f'<span class="num">{hourly(c["from"])} → {hourly(c["to"])}</span>',
                f'<span class="{"down" if (c["pct"] or 0) < 0 else "up"}">{esc(pct(c["pct"]))}</span>',
            ])
        for m in movers[:10]:
            rows.append([
                f'<a href="/instances/{esc(m["type"])}/">{esc(m["type"])}</a>',
                f'<span class="badge">spot · {esc(m["region"])}</span>',
                f'<span class="num">{hourly(m["from"])} → {hourly(m["to"])}</span>',
                f'<span class="{"down" if m["pct"] < 0 else "up"}">{esc(pct(m["pct"]))}</span>',
            ])
        table = b.table([("Instance", False), ("Change type", False), ("From → to", True),
                         ("Change", True)], rows)
        extra = ""
        if new:
            extra += f'<p class="small">New instance types: {", ".join(esc(t) for t in new[:30])}</p>'
        if retired:
            extra += f'<p class="small">Retired instance types: {", ".join(esc(t) for t in retired[:30])}</p>'
        blocks.append(f'<h2>{esc(human_date(doc.get("date", path.stem)))}</h2>{extra}{table}')
    if not blocks:
        blocks.append(
            f'<p class="muted">The change log is empty because the baseline snapshot was collected on '
            f'{esc(human_date(b.today))} and daily comparisons begin with the next collection. '
            f'This page fills in automatically from tomorrow.</p>')

    body = f"""
<h1>AWS price change log</h1>
<p class="lede">AWS does not send a notification when an instance type gets cheaper, when a new
family appears, or when spot capacity quietly gets more expensive. This log records what moved
between consecutive daily collections, newest first.</p>
{''.join(blocks[:20])}
<h2>Why this exists</h2>
<p class="muted">The cheapest instance for a workload is not a fixed answer: previous-generation
families get discounted when they are superseded, new Graviton and Intel generations typically land
at the same price with more performance, and spot prices move daily with demand. Reading this log
once a month is a cheap way to find savings that need no architecture change at all — often it is
just a newer family at the same price. Subscribe below and you will only hear about it when something
meaningful moves.</p>
{b.subscribe_form("Get price change alerts")}
"""
    b.add("/pricing-changes/", "AWS price change log: instance price moves, new and retired types",
          "A daily log of AWS EC2 price changes: on-demand price moves, sizeable spot price shifts, "
          "and new or retired instance types, with the direction of each change.",
          body, priority=0.7,
          breadcrumbs=[("Home", "/"), ("Price change log", "/pricing-changes/")])


def build_api(b: Builder) -> None:
    repo = b.site.get("github_repo", "").replace("https://github.com/", "")
    raw = f"https://raw.githubusercontent.com/{repo}/main"
    body = f"""
<h1>Free daily AWS price data</h1>
<p class="lede">Everything CloudCost Radar collects is published as plain JSON, updated once a day,
free to reuse with attribution. It is the same data the pages on this site are built from, so if
you find an error here, the site is wrong too.</p>
<div class="tablewrap"><table>
<thead><tr><th>Endpoint</th><th>What it contains</th></tr></thead>
<tbody>
<tr><td><a href="{esc(raw)}/api/v1/latest.json" rel="noopener">api/v1/latest.json</a></td>
<td>Every instance type in US East (N. Virginia) with on-demand hourly and monthly price, spot
price and 1-year / 3-year reserved rates.</td></tr>
<tr><td><a href="{esc(raw)}/api/v1/changes.json" rel="noopener">api/v1/changes.json</a></td>
<td>The most recent daily diff: on-demand price changes, new and retired instance types, and spot
movers.</td></tr>
<tr><td><a href="{esc(raw)}/api/v1/regions.json" rel="noopener">api/v1/regions.json</a></td>
<td>Region codes with display names and how many instance types each region sells.</td></tr>
</tbody></table></div>
<h2>Example</h2>
<pre class="mono small" style="background:var(--panel-2);padding:14px;border-radius:10px;overflow:auto">curl -s {raw}/api/v1/latest.json | jq '.instances[] | select(.vcpu == 4 and .ram_gb >= 16) | {{type, on_demand_month}}' | sort -k2</pre>
<h2>Using the data</h2>
<p class="muted">Updated daily around 06:00 UTC. Attribution: a link to
<a href="{esc(b.site.get('base_url'))}">CloudCost Radar</a> is enough. The numbers are published list
prices read from a third-party mirror of the AWS price list, so treat them as a research input rather
than a billing record: always confirm against the provider before you commit money. The collector
validates before publishing (minimum instance counts, price sanity, monthly-equals-hourly
consistency) and refuses to publish at all if validation fails — see the
<a href="/methodology/">methodology</a>.</p>
<h2>Building something with it?</h2>
<p class="muted">A daily-updated price dataset is a reasonable input for cost dashboards, internal
procurement checks or "should we migrate?" one-pagers. If you build something public with it, tell me
and I will link to it: <a href="mailto:{esc(b.site.get('contact_email'))}">{esc(b.site.get('contact_email'))}</a>.
A link back to this site is the only price.</p>
"""
    b.add("/api/", "Free daily AWS EC2 price data (JSON API)",
          "Free, daily-updated JSON endpoints for AWS EC2 on-demand, spot and reserved prices, plus "
          "the daily change log. Reuse with attribution.",
          body, priority=0.8, breadcrumbs=[("Home", "/"), ("Data API", "/api/")])


def build_static_pages(b: Builder) -> None:
    email = b.site.get("contact_email")
    about = f"""
<h1>About CloudCost Radar</h1>
<p class="lede">CloudCost Radar is an independent, self-updating price tracker for cloud compute. It
exists because cloud pricing is public but not actually readable: prices change quietly, they differ
by region, and the same workload can be priced across four purchase models and a dozen providers
before anyone sees the real number.</p>
<h2>What it does</h2>
<ul>
  <li>Collects published AWS EC2 on-demand, spot and reserved prices for
      {b.meta.get('regions_tracked')} regions every day ({b.meta.get('instance_types_total', 0):,} instance
      types at the last collection).</li>
  <li>Diffs them against the previous day and keeps the history permanently.</li>
  <li>Computes the cheapest instance for the sizes people actually buy.</li>
  <li>Puts those prices next to cheaper providers, with an explicit marker on which numbers were
      machine-verified and which were not.</li>
  <li>Publishes everything as free JSON so you do not have to trust the pretty tables.</li>
</ul>
<h2>What it is not</h2>
<p class="muted">It is not affiliated with, endorsed by or sponsored by AWS, and it is not a billing
record. Prices are read from a third-party mirror of the published AWS price list at one moment each
day; AWS can change a price between collections. For anything that matters, confirm on the provider's
own pricing page.</p>
<h2>Corrections</h2>
<p class="muted">If a number is wrong, that is the most useful thing you can tell me —
<a href="mailto:{esc(email)}">{esc(email)}</a>. Corrections get fixed in the next collection.</p>
<div class="btnrow"><a class="btn" href="/methodology/">How collection works</a>
<a class="btn ghost" href="/api/">Get the data</a></div>
"""
    b.add("/about/", "About CloudCost Radar",
          "An independent daily tracker for cloud compute prices: what it covers, what it is not, and "
          "how to report a correction.", about, priority=0.4,
          breadcrumbs=[("Home", "/"), ("About", "/about/")])

    methodology = f"""
<h1>Methodology</h1>
<p class="lede">The rule behind every number on this site: publish what was measured, and publish
nothing when measurement fails.</p>
<h2>Collection</h2>
<p class="muted">Once a day a collector reads the published EC2 price list for
{b.meta.get('regions_tracked')} AWS regions from the public
<a href="https://ec2.shop" rel="noopener">ec2.shop</a> price API, which mirrors AWS's own price list
files. For every instance type it records on-demand hourly price, monthly price, spot price and
reclaim-risk band, and 1-year and 3-year reserved rates (standard and convertible).</p>
<h2>Validation gate</h2>
<p class="muted">Before anything is published the collector checks that the primary region returned at
least 600 instance types, that no region returned fewer than 40, that the total exceeded 2,500, and
that every price is positive and internally consistent (monthly must equal hourly × 730 within 5%;
spot must be no more than twice on-demand). If any check fails, the run aborts, nothing is written,
and the site keeps the last good snapshot. The daily pipeline is idempotent: a given day is collected
exactly once, so today's published figures cannot drift.</p>
<h2>What is never done</h2>
<ul>
  <li>No price is estimated, interpolated, backfilled or hand-edited.</li>
  <li>No price is copied from memory, press coverage or another site.</li>
  <li>No forecast is presented as data.</li>
  <li>Paid placements never change a ranking or a computed "cheapest" result.</li>
</ul>
<h2>Comparisons with other providers</h2>
<p class="muted">Provider plans carry a status. <strong>Verified</strong> means an agent fetched the
provider's own published pricing table on the date shown and recorded that number.
<strong>Live</strong> means the published table could not be machine-read reliably (some providers
render prices in JavaScript), so the site shows no number and links to the source instead. Provider
pricing is re-checked daily for changes, and a changed page is flagged for human re-verification
rather than being silently overwritten.</p>
<h2>Reproducing any number</h2>
<p class="muted">The source of every published figure is in the public repository
(<a href="{esc(b.site.get('github_repo'))}">{esc(b.site.get('github_repo'))}</a>) together with the
daily snapshots, the change log and the spot-price history. Clone it, run the collector, and compare.</p>
<div class="btnrow"><a class="btn" href="/api/">Free data feed</a>
<a class="btn ghost" href="/pricing-changes/">Change log</a></div>
"""
    b.add("/methodology/", "Methodology: how CloudCost Radar collects and validates prices",
          "How CloudCost Radar collects AWS prices daily, the validation gate that blocks a bad "
          "publish, what is never done with the data, and how to reproduce any number.",
          methodology, priority=0.5,
          breadcrumbs=[("Home", "/"), ("Methodology", "/methodology/")])

    disclosure = f"""
<h1>Affiliate disclosure</h1>
<p class="lede">CloudCost Radar costs money to run and takes no subscriptions. Some outbound links to
cloud and VPS providers are referral links: if you sign up through one, the provider may give this
site an account credit or a commission. You do not pay more, and nothing about the price changes.</p>
<h2>The rules this site follows</h2>
<ul>
  <li>Referral links carry the <span class="mono">rel="sponsored nofollow"</span> attribute and a
      visible "referral" badge, so they are never disguised as editorial links.</li>
  <li>Rankings, "cheapest" results and comparison tables are computed from published prices.
      A provider cannot pay to appear higher, and no provider has ever asked to.</li>
  <li>Providers without a referral relationship are still listed if their price is competitive —
      including providers with no affiliate program at all.</li>
  <li>Numbers that could not be machine-verified are shown as "check provider" rather than
      displayed as if verified.</li>
  <li>If a referral relationship exists, it is disclosed on the page where the link appears, not
      only here.</li>
</ul>
<h2>Amazon and AWS</h2>
<p class="muted">CloudCost Radar is not affiliated with, endorsed by or sponsored by Amazon Web
Services. AWS links are not monetised: the site earns nothing when you buy AWS capacity.</p>
<h2>Questions</h2>
<p class="muted">Ask: <a href="mailto:{esc(email)}">{esc(email)}</a>.</p>
"""
    b.add("/affiliate-disclosure/", "Affiliate disclosure",
          "How CloudCost Radar earns money, which links are referral links, and the rules that keep "
          "referral relationships out of rankings and prices.", disclosure, priority=0.4,
          breadcrumbs=[("Home", "/"), ("Affiliate disclosure", "/affiliate-disclosure/")])

    privacy = f"""
<h1>Privacy</h1>
<p class="lede">This site is a static set of pages. It has no accounts, no tracking cookies and no
advertising pixels switched on by default, and it does not sell data.</p>
<h2>What is collected</h2>
<ul>
  <li><strong>Page analytics:</strong> if analytics are enabled, an aggregate, cookie-less pageview
      counter records the page path, referrer and coarse country. No cross-site identifier is stored.</li>
  <li><strong>Email alerts:</strong> if you subscribe, the email address you type is stored so that
      price-change alerts can be sent. That is the only use. Every alert email contains a removal
      link, and you can also ask for deletion at any time.</li>
  <li><strong>Server logs:</strong> the hosting provider keeps standard request logs for security and
      abuse handling.</li>
</ul>
<h2>Advertising</h2>
<p class="muted">If an advertising network is enabled in future, it will be named here and its consent
requirements implemented before any ad is served. The site currently serves no ads.</p>
<h2>Your rights</h2>
<p class="muted">Under GDPR and CCPA/CPRA you can request access to, correction of, or deletion of any
personal data held about you. Write to <a href="mailto:{esc(email)}">{esc(email)}</a> and it will be
handled within 30 days. The lawful basis for holding a subscriber email is consent, which you give
when you submit the form and can withdraw at any time.</p>
"""
    b.add("/privacy/", "Privacy policy",
          "What CloudCost Radar stores: aggregate page analytics, optional email alerts, standard "
          "server logs. No accounts, no tracking cookies, no data sales.", privacy, priority=0.3,
          breadcrumbs=[("Home", "/"), ("Privacy", "/privacy/")])

    contact = f"""
<h1>Contact</h1>
<p class="lede">One person runs this site. The most useful messages are corrections, provider price
changes this tracker has missed, and things you built with the data feed.</p>
<ul class="clean">
  <li><span>Email</span><span><a href="mailto:{esc(email)}">{esc(email)}</a></span></li>
  <li><span>GitHub (code, data, issues)</span><span><a href="{esc(b.site.get('github_repo'))}" rel="noopener">repository</a></span></li>
  <li><span>Free data feed</span><span><a href="/api/">/api/</a></span></li>
</ul>
<p class="muted">Provider correction requests: if you work for a cloud provider and a price or spec
here is wrong, send the published pricing URL and it will be re-verified in the next collection.
Rankings and computed "cheapest" results are not for sale and will not be adjusted on request.</p>
"""
    b.add("/contact/", "Contact CloudCost Radar",
          "Report a correction, a missed price change or a bug. Contact details and the data feed.",
          contact, priority=0.3, breadcrumbs=[("Home", "/"), ("Contact", "/contact/")])


# --------------------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--instance-pages", choices=["all", "watchlist"], default=None,
                        help="Override how many per-instance pages are generated.")
    args = parser.parse_args()

    out = Path(args.out)
    b = Builder(out)
    if not b.rows:
        print("ABORT: no collected data found in data/latest/instances.json - run fetch_data.py first")
        return 2

    mode = args.instance_pages or b.site.get("instance_pages", "all")
    build_home(b)
    build_instances_index(b)
    instance_pages = build_instance_pages(b, mode=mode)
    build_spot(b)
    build_regions(b)
    build_cheapest(b)
    build_gpu(b)
    build_alternatives(b)
    build_compare(b)
    build_calculator(b)
    build_changes(b)
    build_api(b)
    build_static_pages(b)

    result = b.write_all()
    print(f"built {result['pages']} pages ({instance_pages} instance pages) into {out}")
    print(f"assets: {result['assets']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
