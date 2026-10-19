# CloudCost Radar

**Live site:** https://cloudcost-radar.okou.app
**What it is:** a daily-updated cloud compute price tracker — every AWS EC2 instance type with its
on-demand, spot and reserved price across 20 regions, the day-over-day price moves, and an honest
comparison with the cloud/VPS providers that cost less for the same vCPU and RAM.

Built to be a real business, not a demo: 900+ indexable pages, a free JSON data feed, affiliate and
ad slots wired behind config, a newsletter capture, and a daily pipeline that collects, validates,
tests, publishes — or refuses to publish if validation fails.

---

## Why this can earn money

See **[MONETIZATION.md](MONETIZATION.md)** for the full plan with sourced program terms and the
arithmetic to $50/day. The short version:

- **The audience is high intent.** People searching "m7i.large price" or "cheapest 4 vCPU 16 GB
  instance" are choosing where to spend money on infrastructure every month.
- **Referral revenue beats ads early.** Cloud/VPS referral programs pay per referred customer, so a
  few hundred monthly visits can out-earn thousands of ad impressions. Ads (AdSense) switch on later
  once volume exists.
- **The data moat is the daily diff.** Programmatic pages are cheap to generate and worthless
  without unique, fresh data. The change log, spot history and per-instance pages are all derived
  from a price snapshot that is collected and validated once a day.
- **Honest pricing is the product.** Unverifiable numbers are shown as "check provider", never
  guessed. Rankings are computed from published prices and are not for sale.

---

## Architecture

```
src/fetch_data.py      collect + validate one day of AWS prices      -> data/, api/
src/check_providers.py hash provider pricing pages, flag drift       -> data/providers/
src/build_site.py      generate ~920 static pages                    -> site/
src/qa_check.py        publish gate: data, SEO, links, compliance    -> exit 0/1
src/site_base.py       layout, styles, client JS, shared components
config/site.json       branding, base URL, ads, analytics, newsletter
config/affiliates.json referral programs and the policy that guards them
config/alternatives.json curated provider catalog (verified vs verify_live prices)
data/latest/           current state, overwritten daily
data/snapshots/        permanent daily digest
data/changes/          permanent daily change log (prices, new/retired types, spot movers)
data/history/spot/     permanent spot price history
api/v1/                stable JSON endpoints published through GitHub raw
tests/                 regression tests, including the end-to-end build + QA run
```

No runtime dependencies: Python 3.12 standard library only, no framework, no database, no server.
The deployable artefact is a folder of static files.

### What gets generated

| Path | Purpose |
|---|---|
| `/` | Today's board: biggest spot drops, cheapest instance per size class, savings calculator |
| `/instances/` | All 867 instance types, filterable and sortable |
| `/instances/<type>/` | One page per instance type: all purchase models, per-region prices, FAQ |
| `/spot/` | Spot tracker: today's movers, spot-vs-on-demand discounts, reclaim risk |
| `/regions/`, `/regions/<code>/` | Cheapest instance per size class, per region |
| `/cheapest/<n>-vcpu-<n>gb/` | "Cheapest 4 vCPU 16 GB instance" style intent pages |
| `/gpu/`, `/pricing-changes/`, `/calculator/` | GPU pricing, the change log, the cost calculator |
| `/alternatives/`, `/compare/...` | The commercial pages, with verified prices and disclosure |
| `/api/` | Documents the free daily JSON feed |

---

## Daily pipeline

Two independent mechanisms run every day, so a failure in one does not stop the other:

1. **GitHub Actions** (`.github/workflows/daily.yml`, 06:00 UTC daily) — collects the day's prices,
   validates, builds, runs the quality gate and the tests, then commits `data/` and `api/` back to
   this repository. The repo therefore always carries today's data and a stable JSON feed.
2. **Okou agent workflow** (`cloudcost-radar-daily`) — pulls the repo, re-collects if the day is
   missing, rebuilds, runs the gate, captures a fresh cover and redeploys the live site.

Guardrails that matter:

- **Collected once per day.** `--if-missing` makes a day's collection idempotent, so two runs minutes
  apart cannot produce two different published numbers.
- **Validation gate before publish.** Minimum instance counts per region, price positivity,
  monthly = hourly × 730, spot ≤ 2× on-demand. A failed check aborts the run and leaves the previous
  snapshot live.
- **No invented data.** Nothing is estimated, backfilled, smoothed or hand-edited — enforced by
  `tests/test_pipeline.py`, which fails if an unverified provider price carries a number.

---

## Running it locally

```bash
make collect   # fetch today's prices (skips if already collected)
make build     # generate site/
make qa        # publish gate: must print PASS
make test      # regression tests
make serve     # preview on http://localhost:8000

make daily     # collect + provider drift check + build + qa  (what CI runs)
make publish   # capture a cover and redeploy the hosted site
```

Individual steps:

```bash
python3 src/fetch_data.py --if-missing          # collect once per day
python3 src/fetch_data.py --reuse-raw           # rebuild artefacts from cached raw responses
python3 src/build_site.py --out site --instance-pages watchlist   # smaller build for quick checks
```

---

## Configuration

### `config/site.json`
Domain, branding, contact address, tracked regions, ad slots, analytics token, newsletter endpoint.

### `config/affiliates.json`
One entry per provider program with `status`, `public_url` and an empty `ref_url`. **Fill in
`ref_url` only after you are accepted into a program.** Until then the site links to the provider's
normal pricing page with no tracking and displays no "referral" badge. `qa_check.py` fails the build
if a placeholder code is present. The `policy` block is what keeps referral relationships out of
rankings, and the site renders a visible disclosure wherever a sponsored link appears.

### `config/alternatives.json`
The provider comparison catalog. Every plan carries a `price_status`:

- `verified` — an agent read the number from the provider's published pricing table on `verified_at`.
- `verify_live` — the published table could not be machine-read reliably (JavaScript-rendered), so
  the site shows **no number** and links to the source instead.

`src/check_providers.py` re-hashes every provider pricing page daily and flags a change for human
re-verification rather than silently overwriting a price. Three providers (Vultr, Linode, Contabo)
return HTTP 403 to automated fetches; that is recorded as `http_403`, not hidden.

### Turning on ads, analytics and email alerts
All three are off by default and enabled purely through config:

- **Ads:** set `ads.enabled: true`, `ads.client` (e.g. `ca-pub-…`) and the slot IDs. `ads.txt` is
  generated automatically when enabled.
- **Analytics:** set `analytics.enabled: true` and a Cloudflare Web Analytics token (cookie-less).
- **Email alerts:** set `newsletter.enabled: true` with the Supabase project URL, anon key and table
  name. The page states plainly that nothing is stored while alerts are off, rather than pretending
  a subscription succeeded.

---

## Quality gate

`python3 src/qa_check.py --out site` must print `PASS`. It verifies data integrity, required pages,
unique titles and descriptions, canonical URLs, valid JSON-LD, internal link and asset integrity,
sitemap ↔ page consistency, robots.txt, that sponsored links carry `rel="sponsored nofollow"`, that
monetised pages carry a disclosure, that no placeholder or guarantee language leaked into the copy,
and that no ad markup appears while ads are disabled.

## Data sources and honesty rules

- Prices come from the public, keyless [ec2.shop](https://ec2.shop) EC2 price API, which mirrors AWS's
  published price list files. Read the **methodology page** (`/methodology/`) for the exact checks.
- AWS prices are list prices, not billing records. Every page carries a "confirm with the provider"
  notice and an explicit statement that this site is not affiliated with AWS.
- Provider prices are only shown when they were machine-verified; everything else says "check
  provider".
- Corrections are welcome and are the most useful thing you can send: see the contact page.

## Licence

Code: MIT. Collected price data: free to reuse with attribution. See [LICENSE](LICENSE).
