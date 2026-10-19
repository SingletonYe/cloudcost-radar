#!/usr/bin/env python3
"""CloudCost Radar - static site builder.

Reads the collected data plus the config files and writes a complete static site into
`site/`. No network access, no templating dependencies: plain stdlib string building so the
daily pipeline (GitHub Actions + the Okou agent workflow) is deterministic and fast.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_OUT = ROOT / "site"

SPEC_PAGES = [
    (1, 1), (1, 2), (2, 2), (2, 4), (2, 8), (4, 8), (4, 16), (8, 16), (8, 32), (16, 32), (16, 64),
]

COMPARE_PAGES = [
    ("aws-ec2-vs-digitalocean", "AWS EC2 vs DigitalOcean"),
    ("aws-ec2-vs-vultr", "AWS EC2 vs Vultr"),
    ("aws-ec2-vs-hetzner", "AWS EC2 vs Hetzner Cloud"),
    ("aws-ec2-vs-linode", "AWS EC2 vs Akamai / Linode"),
    ("aws-ec2-vs-lightsail", "AWS EC2 vs Amazon Lightsail"),
    ("hetzner-vs-digitalocean", "Hetzner Cloud vs DigitalOcean"),
]

NAV = [
    ("/", "Today"),
    ("/instances/", "Instance prices"),
    ("/spot/", "Spot prices"),
    ("/cheapest/", "Cheapest by size"),
    ("/gpu/", "GPU"),
    ("/regions/", "Regions"),
    ("/alternatives/", "Alternatives"),
    ("/calculator/", "Calculator"),
    ("/api/", "Data API"),
]


# --------------------------------------------------------------------------- utils

def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def usd(value, places: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.{places}f}"


def usd_precise(value) -> str:
    """Hourly prices need more decimals than monthly ones."""
    if value is None:
        return "n/a"
    if value >= 1:
        return f"${value:,.4f}"
    return f"${value:.4f}"


def pct(value) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def human_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        return iso or ""


def human_date_short(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%b %-d, %Y")
    except (ValueError, TypeError):
        return iso or ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


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


def is_watchlisted(itype: str) -> bool:
    if "." not in itype:
        return False
    family, size = itype.split(".", 1)
    return family in WATCH_FAMILIES and size in WATCH_SIZES


# --------------------------------------------------------------------------- assets

CSS = """
:root{
  --bg:#0b1220; --panel:#121b2e; --panel-2:#17223a; --line:#243149;
  --ink:#eef2f9; --muted:#9aa8c0; --accent:#37d6a3; --accent-2:#4aa8ff;
  --warn:#ffb454; --danger:#ff7a7a; --radius:14px;
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:linear-gradient(180deg,#0a101c,#0b1220 320px);color:var(--ink);
  font-family:var(--font);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:var(--accent-2);text-decoration:none}
a:hover{text-decoration:underline}
img{max-width:100%}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
header.site{position:sticky;top:0;z-index:20;background:rgba(10,16,28,.92);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
header.site .bar{display:flex;align-items:center;gap:18px;padding:12px 0;flex-wrap:wrap}
.brand{font-weight:700;color:var(--ink);font-size:18px;letter-spacing:-.2px}
.brand span{color:var(--accent)}
nav.main{display:flex;gap:14px;flex-wrap:wrap;font-size:14px}
nav.main a{color:var(--muted)}
nav.main a:hover{color:var(--ink);text-decoration:none}
.updated{margin-left:auto;font-size:13px;color:var(--muted);white-space:nowrap}
main{padding:28px 0 60px}
h1{font-size:clamp(26px,4vw,38px);line-height:1.18;margin:6px 0 10px;letter-spacing:-.5px}
h2{font-size:23px;margin:34px 0 12px;letter-spacing:-.3px}
h3{font-size:18px;margin:22px 0 8px}
p{margin:10px 0;color:#dbe3f0}
.lede{color:var(--muted);font-size:17px;max-width:70ch}
.crumbs{font-size:13px;color:var(--muted);margin-bottom:6px}
.crumbs a{color:var(--muted)}
.grid{display:grid;gap:16px}
.grid.c2{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.grid.c3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.grid.c4{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:18px}
.card h3{margin-top:0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px}
.stat .k{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.stat .v{font-size:24px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.stat .s{font-size:13px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:15px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line)}
th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--mono);font-size:14px}
tbody tr:hover{background:rgba(74,168,255,.06)}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel)}
.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);
  color:var(--muted);background:var(--panel-2)}
.badge.good{color:#0b1220;background:var(--accent);border-color:var(--accent);font-weight:600}
.badge.hot{color:#0b1220;background:var(--warn);border-color:var(--warn);font-weight:600}
.badge.ref{color:#0b1220;background:var(--accent-2);border-color:var(--accent-2);font-weight:600}
.down{color:var(--accent);font-weight:600}
.up{color:var(--danger);font-weight:600}
.btn{display:inline-block;padding:10px 16px;border-radius:10px;font-weight:600;
  background:var(--accent);color:#07231a;border:1px solid var(--accent)}
.btn:hover{text-decoration:none;filter:brightness(1.06)}
.btn.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
.btn.small{padding:6px 11px;font-size:14px}
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.notice{border-left:3px solid var(--accent-2);background:var(--panel-2);padding:12px 14px;border-radius:8px;
  font-size:14px;color:#cfd8e8;margin:16px 0}
.notice.disclosure{border-left-color:var(--warn)}
footer.site{border-top:1px solid var(--line);padding:28px 0 40px;color:var(--muted);font-size:14px}
footer.site .cols{display:grid;gap:20px;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-bottom:18px}
footer.site a{color:#c8d3e6}
input,select,button{font-family:inherit;font-size:15px}
input,select{background:var(--panel-2);border:1px solid var(--line);color:var(--ink);
  border-radius:9px;padding:9px 11px;width:100%}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
.calc-out{font-family:var(--mono);font-size:15px}
.muted{color:var(--muted)}
.small{font-size:13px}
.mono{font-family:var(--mono)}
.ad{margin:22px 0;padding:10px;border:1px dashed var(--line);border-radius:10px;text-align:center;
  color:var(--muted);font-size:13px;min-height:60px}
ul.clean{list-style:none;padding:0;margin:8px 0}
ul.clean li{padding:7px 0;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:baseline;justify-content:space-between}
ul.clean li:last-child{border-bottom:none}
.tick{color:var(--accent);font-weight:700}
.faq h3{margin-bottom:4px}
.faq p{margin-top:0;color:#cfd8e8}
@media(max-width:720px){
  .updated{width:100%;margin-left:0}
  table{font-size:14px}
  th,td{padding:8px 7px}
  .stat .v{font-size:20px}
}
"""

APP_JS = """
(function(){
  var CC = window.CC || {};
  function q(sel,root){return (root||document).querySelector(sel);}
  function qa(sel,root){return Array.prototype.slice.call((root||document).querySelectorAll(sel));}
  function money(v,p){ if(v===null||v===undefined||isNaN(v)) return 'n/a';
    return '$'+Number(v).toFixed(p===undefined?2:p); }
  function hourly(v){ if(v===null||v===undefined||isNaN(v)) return 'n/a';
    return '$'+Number(v).toFixed(4); }

  /* ---- instance table: filter + sort ---- */
  var table = q('#instances-table');
  if (table && CC.instances) {
    var tbody = q('tbody', table);
    var filters = {search:'', minVcpu:0, maxHour:null, family:'', gpu:false};
    var ROWS = CC.instances.map(function(r){
      return {type:r[0],vcpu:r[1],mem:r[2],od:r[3],spot:r[4],r1:r[5],r3:r[6],gpu:r[7],family:r[0].split('.')[0]};
    });
    function render(){
      var term = filters.search.trim().toLowerCase();
      var out = ROWS.filter(function(r){
        if (filters.gpu && !r.gpu) return false;
        if (filters.family && r.family !== filters.family) return false;
        if (r.vcpu < filters.minVcpu) return false;
        if (filters.maxHour !== null && r.od > filters.maxHour) return false;
        if (term && r.type.toLowerCase().indexOf(term) === -1) return false;
        return true;
      });
      var sortKey = table.getAttribute('data-sort') || 'od';
      var dir = table.getAttribute('data-dir') === 'desc' ? -1 : 1;
      out.sort(function(a,b){
        var av = a[sortKey], bv = b[sortKey];
        if (av === null) av = Infinity; if (bv === null) bv = Infinity;
        if (typeof av === 'string') return av.localeCompare(bv) * dir;
        return (av - bv) * dir;
      });
      var limit = Math.min(out.length, 300);
      tbody.innerHTML = out.slice(0, limit).map(function(r){
        return '<tr><td><a href="/instances/'+r.type+'.html">'+r.type+'</a></td>'+
          '<td class="num">'+r.vcpu+'</td><td class="num">'+Number(r.mem).toFixed(r.mem%1?1:0)+'</td>'+
          '<td class="num">'+hourly(r.od)+'</td><td class="num">'+money(r.od*730)+'</td>'+
          '<td class="num">'+(r.spot?hourly(r.spot):'n/a')+'</td>'+
          '<td class="num">'+(r.r1?hourly(r.r1):'n/a')+'</td>'+
          '<td>'+(r.gpu?'<span class="badge hot">GPU</span>':'')+'</td></tr>';
      }).join('');
      var countEl = q('#instance-count');
      if (countEl) countEl.textContent = out.length.toLocaleString()+' instance types match';
      var note = q('#instance-limit-note');
      if (note) note.style.display = out.length > limit ? 'block' : 'none';
    }
    qa('#instances-table th[data-key]').forEach(function(th){
      th.style.cursor = 'pointer';
      th.addEventListener('click', function(){
        var key = th.getAttribute('data-key');
        if (table.getAttribute('data-sort') === key) {
          table.setAttribute('data-dir', table.getAttribute('data-dir') === 'desc' ? 'asc' : 'desc');
        } else {
          table.setAttribute('data-sort', key); table.setAttribute('data-dir', 'asc');
        }
        render();
      });
    });
    var search = q('#instance-search');
    if (search) search.addEventListener('input', function(){ filters.search = search.value; render(); });
    var fam = q('#instance-family');
    if (fam) fam.addEventListener('change', function(){ filters.family = fam.value; render(); });
    var vc = q('#instance-vcpu');
    if (vc) vc.addEventListener('change', function(){ filters.minVcpu = Number(vc.value); render(); });
    var mx = q('#instance-max');
    if (mx) mx.addEventListener('change', function(){ filters.maxHour = mx.value ? Number(mx.value) : null; render(); });
    var ga = q('#instance-gpu');
    if (ga) ga.addEventListener('change', function(){ filters.gpu = ga.checked; render(); });
    var all = q('#instance-reset');
    if (all) all.addEventListener('click', function(){
      filters = {search:'', minVcpu:0, maxHour:null, family:'', gpu:false};
      if (search) search.value=''; if (fam) fam.value=''; if (vc) vc.value='0';
      if (mx) mx.value=''; if (ga) ga.checked=false;
      table.setAttribute('data-sort','od'); table.setAttribute('data-dir','asc'); render();
    });
    render();
  }

  /* ---- savings calculator ---- */
  var calc = q('#calculator');
  if (calc && CC.instances) {
    var ROWS = CC.instances.map(function(r){
      return {type:r[0],vcpu:r[1],mem:r[2],od:r[3],spot:r[4],r1:r[5],r3:r[6],gpu:r[7]};
    });
    function run(){
      var vcpu = Number(q('#calc-vcpu').value||2);
      var ram = Number(q('#calc-ram').value||4);
      var count = Number(q('#calc-count').value||1);
      var match = ROWS.filter(function(r){ return r.vcpu === vcpu && r.mem >= ram; })
        .sort(function(a,b){ return a.od - b.od; });
      var pool = match.length ? match : ROWS.slice().sort(function(a,b){ return a.od - b.od; });
      var best = pool[0];
      var out = q('#calc-out');
      if (!best) { out.innerHTML = '<p class="muted">No matching instance types.</p>'; return; }
      var odMonthly = best.od * 730 * count;
      var spotMonthly = best.spot ? best.spot * 730 * count : null;
      var r1 = pool.filter(function(r){ return r.r1; }).sort(function(a,b){ return a.r1 - b.r1; })[0];
      var r3 = pool.filter(function(r){ return r.r3; }).sort(function(a,b){ return a.r3 - b.r3; })[0];
      var rows = '';
      rows += '<tr><td>Cheapest on-demand</td><td>'+best.type+'</td><td class="num">'+money(odMonthly)+
              '</td><td class="num muted">baseline</td></tr>';
      if (spotMonthly) rows += '<tr><td>Same instance on spot</td><td>'+best.type+
              '</td><td class="num">'+money(spotMonthly)+'</td><td class="num down">-'+
              money(odMonthly-spotMonthly)+'/mo</td></tr>';
      if (r1) rows += '<tr><td>1-year reserved (no upfront)</td><td>'+r1.type+'</td><td class="num">'+
              money(r1.r1*730*count)+'</td><td class="num down">-'+money(odMonthly-r1.r1*730*count)+'/mo</td></tr>';
      if (r3) rows += '<tr><td>3-year reserved (no upfront)</td><td>'+r3.type+'</td><td class="num">'+
              money(r3.r3*730*count)+'</td><td class="num down">-'+money(odMonthly-r3.r3*730*count)+'/mo</td></tr>';
      out.innerHTML = '<div class="tablewrap"><table><thead><tr><th>Option</th><th>Instance</th>'+
        '<th class="num">Monthly</th><th class="num">vs on-demand</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
        '<p class="small muted">Estimated from today\'s published US East (N. Virginia) prices, '+
        count+' instance(s) running 730 hours. Spot capacity can be reclaimed.</p>';
    }
    qa('#calculator input, #calculator select').forEach(function(el){
      el.addEventListener('change', run); el.addEventListener('input', run);
    });
    run();
  }

  /* ---- newsletter form ---- */
  var form = q('#subscribe-form');
  if (form) {
    form.addEventListener('submit', function(ev){
      ev.preventDefault();
      var msg = q('#subscribe-msg');
      var email = q('#subscribe-email').value;
      if (CC.newsletter && CC.newsletter.enabled) {
        fetch(CC.newsletter.url, {
          method:'POST',
          headers:{'Content-Type':'application/json','apikey':CC.newsletter.key,
                   'Authorization':'Bearer '+CC.newsletter.key,'Prefer':'return=minimal'},
          body: JSON.stringify({email:email, source:'cloudcost-radar'})
        }).then(function(r){
          if (r.ok) { msg.textContent = 'You are on the list. Alerts are sent only on real price changes.'; form.reset(); }
          else { msg.textContent = 'Could not save that right now - please try again later.'; }
        }).catch(function(){ msg.textContent = 'Could not save that right now - please try again later.'; });
      } else {
        msg.textContent = 'Alerts are not switched on yet, so nothing was stored. The daily price feed at /api/ is already live and free.';
      }
    });
  }
})();
"""


# --------------------------------------------------------------------------- builder

class Builder:
    def __init__(self, out_dir: Path):
        self.out = out_dir
        self.site = load_json(ROOT / "config" / "site.json", {})
        self.affiliates = load_json(ROOT / "config" / "affiliates.json", {"programs": []})
        self.alternatives = load_json(ROOT / "config" / "alternatives.json", {"providers": []})
        self.instances_doc = load_json(DATA / "latest" / "instances.json", {})
        self.regions_doc = load_json(DATA / "latest" / "regions.json", {"regions": {}})
        self.meta = load_json(DATA / "latest" / "meta.json", {})
        self.pages: list[dict] = []
        self.rows = self.instances_doc.get("instances", [])
        self.today = self.instances_doc.get("date") or datetime.now(timezone.utc).date().isoformat()
        self.gpu_pointer = self._gpu_pointer()

    # -- affiliate helpers -------------------------------------------------
    def program(self, provider_id: str) -> dict:
        for prog in self.affiliates.get("programs", []):
            if prog.get("id") == provider_id:
                return prog
        return {}

    def provider_link(self, provider_id: str, public_url: str, label: str, small: bool = True) -> str:
        """Outbound provider link. Uses the referral URL only when a real one is configured."""
        prog = self.program(provider_id)
        ref_url = (prog.get("ref_url") or "").strip()
        has_ref = bool(ref_url) and "YOUR" not in ref_url.upper()
        url = ref_url if has_ref else public_url
        rel = self.affiliates.get("policy", {}).get("link_rel", "sponsored nofollow noopener")
        attrs = f' rel="{esc(rel)}"' if has_ref else ' rel="noopener"'
        badge = ' <span class="badge ref">referral</span>' if has_ref else ""
        klass = "btn small" if small else "btn"
        return f'<a class="{klass}" href="{esc(url)}"{attrs} target="_blank">{esc(label)}</a>{badge}'

    # -- data helpers ------------------------------------------------------
    def _gpu_pointer(self):
        gpu = [r for r in self.rows if r.get("gpu")]
        return gpu

    def cheapest(self, vcpu: int | None = None, min_mem: float | None = None,
                 gpu_only: bool = False, limit: int = 10) -> list[dict]:
        pool = self.rows
        if vcpu is not None:
            pool = [r for r in pool if r["vcpu"] == vcpu]
        if min_mem is not None:
            pool = [r for r in pool if r["mem_gb"] >= min_mem]
        if gpu_only:
            pool = [r for r in pool if r.get("gpu")]
        return sorted(pool, key=lambda r: r["od_hour"])[:limit]

    def similar(self, row: dict, limit: int = 8) -> list[dict]:
        pool = [r for r in self.rows
                if r["type"] != row["type"] and r["vcpu"] == row["vcpu"]
                and abs(r["mem_gb"] - row["mem_gb"]) <= max(2.0, row["mem_gb"] * 0.3)]
        return sorted(pool, key=lambda r: abs(r["od_hour"] - row["od_hour"]))[:limit]

    def region_options(self) -> list[dict]:
        return [
            {"code": code, "name": info.get("name", code), "bucket": info.get("bucket", ""),
             "rows": info.get("rows", [])}
            for code, info in self.regions_doc.get("regions", {}).items()
        ]

    def spot_history_days(self) -> list[Path]:
        hist = DATA / "history" / "spot"
        if not hist.exists():
            return []
        return sorted(hist.glob("*.json"))

    def changes_days(self) -> list[Path]:
        ch = DATA / "changes"
        if not ch.exists():
            return []
        return sorted(ch.glob("*.json"), reverse=True)

    # -- page plumbing -----------------------------------------------------
    def url_for(self, path: str) -> str:
        """Public URL for a logical path.

        The host serves exact file paths (no directory-index rewriting), so every logical
        directory path becomes a flat `.html` URL: /instances/ -> /instances.html
        and /instances/m7i.large/ -> /instances/m7i.large.html.
        """
        base = self.site.get("base_url", "").rstrip("/")
        if path == "/":
            return base + "/"
        if path.endswith("/"):
            return base + path.rstrip("/") + ".html"
        return base + path

    def file_for(self, path: str) -> str:
        """Output file path inside the bundle for a logical path."""
        if path == "/":
            return "index.html"
        return path.lstrip("/").rstrip("/") + ".html" if path.endswith("/") else path.lstrip("/")

    @staticmethod
    def html_links_to_flat_urls(text: str) -> str:
        """Rewrite internal directory links to their flat .html form."""
        return re.sub(r'href="(/[^"]*?)/"', r'href="\1.html"', text)

    def add(self, path: str, title: str, description: str, body: str, *,
            jsonld: list[dict] | None = None, priority: float = 0.6,
            changefreq: str = "daily", extra_head: str = "", noindex: bool = False,
            breadcrumbs: list[tuple[str, str]] | None = None) -> None:
        self.pages.append({
            "path": path, "title": title, "description": description, "body": body,
            "jsonld": jsonld or [], "priority": priority, "changefreq": changefreq,
            "extra_head": extra_head, "noindex": noindex, "breadcrumbs": breadcrumbs or [],
        })

    def write_all(self) -> dict:
        if self.out.exists():
            shutil.rmtree(self.out)
        (self.out / "assets").mkdir(parents=True, exist_ok=True)
        self.assets = {}

        css_hash = hashlib.sha256(CSS.encode()).hexdigest()[:8]
        js_hash = hashlib.sha256(APP_JS.encode()).hexdigest()[:8]
        css_name = f"site-{css_hash}.css"
        js_name = f"app-{js_hash}.js"
        (self.out / "assets" / css_name).write_text(CSS, encoding="utf-8")
        (self.out / "assets" / js_name).write_text(APP_JS, encoding="utf-8")

        data_payload = self.build_data_asset()
        data_json = json.dumps(data_payload, separators=(",", ":"))
        data_hash = hashlib.sha256(data_json.encode()).hexdigest()[:8]
        data_name = f"data-{data_hash}.js"
        (self.out / "assets" / data_name).write_text(
            "window.CC=" + data_json + ";\n", encoding="utf-8")

        self.assets = {"css": css_name, "js": js_name, "data": data_name}

        for page in self.pages:
            target = self.out / self.file_for(page["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.render_page(page), encoding="utf-8")

        self.write_sitemap()
        self.write_robots()
        self.write_404()
        self.write_ads_txt()
        return {"pages": len(self.pages), "assets": self.assets}

    def build_data_asset(self) -> dict:
        instances = [
            [r["type"], r["vcpu"], r["mem_gb"], r["od_hour"], r["spot_hour"], r["r1y_hour"],
             r["r3y_hour"], r["gpu"]]
            for r in self.rows
        ]
        programs = {}
        for prog in self.affiliates.get("programs", []):
            ref = (prog.get("ref_url") or "").strip()
            programs[prog["id"]] = {
                "name": prog.get("name"),
                "url": ref if ref and "YOUR" not in ref.upper() else prog.get("public_url"),
                "has_ref": bool(ref) and "YOUR" not in ref.upper(),
            }
        newsletter = self.site.get("newsletter", {})
        nl_enabled = bool(newsletter.get("enabled") and newsletter.get("supabase_url")
                          and newsletter.get("supabase_anon_key"))
        return {
            "instances": instances,
            "region": self.instances_doc.get("region"),
            "date": self.today,
            "affiliates": programs,
            "newsletter": {
                "enabled": nl_enabled,
                "url": f"{newsletter.get('supabase_url','').rstrip('/')}/rest/v1/"
                       f"{newsletter.get('table','subscribers')}" if nl_enabled else "",
                "key": newsletter.get("supabase_anon_key", "") if nl_enabled else "",
            },
        }

    def render_page(self, page: dict) -> str:
        site = self.site
        canonical = self.url_for(page["path"])
        robots = "noindex,nofollow" if page["noindex"] else "index,follow,max-image-preview:large"
        ld_blocks = list(page["jsonld"])
        ld_blocks.insert(0, {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": site.get("name"),
            "url": site.get("base_url"),
            "description": site.get("description"),
        })
        if page["breadcrumbs"]:
            ld_blocks.append({
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "name": name,
                     "item": self.url_for(path)}
                    for i, (name, path) in enumerate(page["breadcrumbs"])
                ],
            })
        ld_html = "\n".join(
            f'<script type="application/ld+json">{json.dumps(block, separators=(",", ":"))}</script>'
            for block in ld_blocks
        )
        nav_html = "".join(
            f'<a href="{esc(path)}">{esc(label)}</a>' for path, label in NAV
        )
        analytics = ""
        if site.get("analytics", {}).get("enabled") and site.get("analytics", {}).get("token"):
            analytics = (
                '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
                f'data-cf-beacon=\'{{"token": "{esc(site["analytics"]["token"])}"}}\'></script>'
            )
        crumbs = ""
        if page["breadcrumbs"]:
            parts = []
            for i, (name, path) in enumerate(page["breadcrumbs"]):
                if i == len(page["breadcrumbs"]) - 1:
                    parts.append(esc(name))
                else:
                    parts.append(f'<a href="{esc(path)}">{esc(name)}</a>')
            crumbs = '<div class="crumbs">' + " › ".join(parts) + "</div>"

        footer = ""
        disclaimer = (
            f'<div class="notice disclosure small">Prices are the published list prices read from the '
            f'upstream source on {esc(human_date_short(self.today))}. '
            f'Cloud providers change pricing without notice: confirm on the provider page before you commit. '
            f'<a href="/affiliate-disclosure/">Some outbound provider links are referral links.</a></div>'
        )
        document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(page['title'])}</title>
<meta name="description" content="{esc(page['description'])}">
<meta name="robots" content="{esc(robots)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(site.get('name'))}">
<meta property="og:title" content="{esc(page['title'])}">
<meta property="og:description" content="{esc(page['description'])}">
<meta property="og:url" content="{esc(canonical)}">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/json" href="https://raw.githubusercontent.com/SingletonYe/cloudcost-radar/main/api/v1/latest.json" title="Daily JSON price feed">
<link rel="stylesheet" href="/assets/{esc(self.assets['css'])}">
{analytics}
{page['extra_head']}
{ld_html}
</head>
<body>
<header class="site"><div class="wrap bar">
  <div class="brand"><a href="/" style="color:inherit">CloudCost<span>Radar</span></a></div>
  <nav class="main">{nav_html}</nav>
  <div class="updated">Updated {esc(human_date_short(self.today))} · {(self.meta.get('instance_types_total') or 0):,} prices</div>
</div></header>
<main><div class="wrap">
{crumbs}
{page['body']}
{disclaimer}
</div></main>
<footer class="site"><div class="wrap">
  <div class="cols">
    <div>
      <strong style="color:var(--ink)">CloudCost Radar</strong>
      <p class="small">Independent daily tracking of cloud compute prices: AWS EC2 on-demand, spot and
      reserved rates across {(self.meta.get('regions_tracked') or 0)} regions, plus cheaper alternatives.</p>
    </div>
    <div>
      <strong style="color:var(--ink)">Prices</strong>
      <ul class="clean small">
        <li><a href="/instances/">All instance prices</a></li>
        <li><a href="/spot/">Spot price tracker</a></li>
        <li><a href="/gpu/">GPU instances</a></li>
        <li><a href="/pricing-changes/">Price change log</a></li>
      </ul>
    </div>
    <div>
      <strong style="color:var(--ink)">Save money</strong>
      <ul class="clean small">
        <li><a href="/alternatives/">Cheaper alternatives</a></li>
        <li><a href="/calculator/">Savings calculator</a></li>
        <li><a href="/api/">Free price data API</a></li>
      </ul>
    </div>
    <div>
      <strong style="color:var(--ink)">About</strong>
      <ul class="clean small">
        <li><a href="/methodology/">Methodology</a></li>
        <li><a href="/affiliate-disclosure/">Affiliate disclosure</a></li>
        <li><a href="/privacy/">Privacy</a></li>
        <li><a href="{esc(site.get('github_repo'))}">Source on GitHub</a></li>
      </ul>
    </div>
  </div>
  <p class="small">Data source: {esc(', '.join(s.get('name', '') for s in site.get('data_sources', [])))}.
  Contact: <a href="mailto:{esc(site.get('contact_email'))}">{esc(site.get('contact_email'))}</a>.
  This site is not affiliated with, endorsed by, or sponsored by Amazon Web Services.</p>
</div></footer>
<script src="/assets/{esc(self.assets['data'])}"></script>
<script src="/assets/{esc(self.assets['js'])}" defer></script>
</body>
</html>
"""
        return self.html_links_to_flat_urls(document)

    def write_sitemap(self) -> None:
        build_marker = hashlib.sha256(
            json.dumps([p["path"] for p in self.pages]).encode()
            + self.today.encode()
        ).hexdigest()[:12]
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 f'<!-- cloudcost-radar build {build_marker} {self.today} -->',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for page in self.pages:
            if page["noindex"]:
                continue
            lines.append(
                f'  <url><loc>{esc(self.url_for(page["path"]))}</loc>'
                f'<lastmod>{esc(self.today)}</lastmod>'
                f'<changefreq>{esc(page["changefreq"])}</changefreq>'
                f'<priority>{page["priority"]:.1f}</priority></url>'
            )
        lines.append('</urlset>')
        (self.out / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_robots(self) -> None:
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /404.html\n\n"
            f"Sitemap: {self.url_for('/sitemap.xml')}\n"
        )
        (self.out / "robots.txt").write_text(body, encoding="utf-8")

    def write_ads_txt(self) -> None:
        ads = self.site.get("ads", {})
        client = (ads.get("client") or "").strip()
        if ads.get("enabled") and client:
            pub = client.replace("ca-", "")
            (self.out / "ads.txt").write_text(
                f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")

    def write_404(self) -> None:
        body = ("<h1>Page not found</h1><p class='lede'>That page does not exist. "
                "Start from today's price board.</p>"
                "<div class='btnrow'><a class='btn' href='/'>Today's AWS prices</a>"
                "<a class='btn ghost' href='/instances/'>All instance prices</a></div>")
        page = {"path": "/404.html", "title": "Page not found - CloudCost Radar",
                "description": "Page not found.", "body": body, "jsonld": [],
                "priority": 0.0, "changefreq": "monthly", "extra_head": "", "noindex": True,
                "breadcrumbs": []}
        (self.out / "404.html").write_text(self.render_page(page), encoding="utf-8")

    # -- shared fragments --------------------------------------------------
    def ad_slot(self, key: str) -> str:
        ads = self.site.get("ads", {})
        if not ads.get("enabled") or not ads.get("client") or not ads.get("slots", {}).get(key):
            return ""
        return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" '
                f'data-ad-client="{esc(ads["client"])}" data-ad-slot="{esc(ads["slots"][key])}" '
                f'data-ad-format="auto" data-full-width-responsive="true"></ins></div>')

    def subscribe_form(self, heading: str = "Get price-drop alerts") -> str:
        return f"""
<section class="card" id="subscribe">
  <h3>{esc(heading)}</h3>
  <p class="small muted">One email when something that matters changes: an AWS on-demand price move,
  a headline spot-price shift, or a new cheaper instance type. No daily noise.</p>
  <form id="subscribe-form" style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-top:10px">
    <div style="flex:1;min-width:220px">
      <label for="subscribe-email">Email address</label>
      <input id="subscribe-email" type="email" name="email" required placeholder="you@company.com">
    </div>
    <button class="btn" type="submit">Subscribe</button>
  </form>
  <p class="small" id="subscribe-msg" style="margin-top:8px"></p>
</section>"""

    def table(self, headers: list[tuple], rows: list[list[str]],
              table_id: str = "", sort_key: str = "od") -> str:
        """headers: (label, is_numeric) or (label, is_numeric, sort_key).

        rows are sequences of already-escaped cell HTML; this wraps them in <td> using the
        column alignment implied by headers."""
        cells = []
        numeric = []
        for header in headers:
            label, is_num = header[0], header[1]
            key = header[2] if len(header) > 2 else None
            numeric.append(bool(is_num))
            key_attr = f' data-key="{esc(key)}"' if (key and table_id) else ""
            cells.append(f'<th class="{"num" if is_num else ""}"{key_attr}>{esc(label)}</th>')
        head = "".join(cells)
        body_rows = []
        for row_cells in rows:
            tds = []
            for index, cell in enumerate(row_cells):
                is_num = numeric[index] if index < len(numeric) else False
                tds.append(f'<td class="{"num" if is_num else ""}">{cell}</td>')
            body_rows.append("<tr>" + "".join(tds) + "</tr>")
        ident = f' id="{esc(table_id)}" data-sort="{esc(sort_key)}" data-dir="asc"' if table_id else ""
        return (f'<div class="tablewrap"><table{ident}><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(body_rows)}</tbody></table></div>')

    def stat(self, label: str, value: str, sub: str = "") -> str:
        return (f'<div class="stat"><div class="k">{esc(label)}</div>'
                f'<div class="v">{value}</div>'
                f'<div class="s">{esc(sub)}</div></div>')

    def change_rows(self, changes: dict) -> str:
        """HTML list of today's on-demand and spot movement."""
        out = []
        od = changes.get("on_demand_changes") or []
        if od:
            items = "".join(
                f'<li><a href="/instances/{esc(c["type"])}/">{esc(c["type"])}</a>'
                f'<span class="{"down" if (c["pct"] or 0) < 0 else "up"}">{esc(pct(c["pct"]))}</span></li>'
                for c in od[:10]
            )
            out.append(f"<h3>On-demand price changes ({len(od)})</h3><ul class='clean'>{items}</ul>")
        movers = changes.get("spot_movers") or []
        if movers:
            items = "".join(
                f'<li><a href="/instances/{esc(m["type"])}/">{esc(m["type"])}</a>'
                f'<span class="muted small">{esc(m["region"])}</span>'
                f'<span class="{"down" if m["pct"] < 0 else "up"}">{esc(pct(m["pct"]))}</span></li>'
                for m in movers[:10]
            )
            out.append(f"<h3>Biggest spot movers ({len(movers)})</h3><ul class='clean'>{items}</ul>")
        return "".join(out)
