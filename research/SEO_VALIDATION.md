# Search demand validation

Measured with DataForSEO through the Okou SEO interface on 2026-10-19. Raw responses are in
`research/kw-*.json` and `research/serp-*.json` so the numbers can be re-checked later.

The point of this note is to test one assumption before spending months on it: **do the page types
this site generates map to queries that advertisers pay real money for, and can a small site
realistically rank there?**

## 1. The money is real: commercial CPC in this niche is high

135,000+ keyword ideas were returned for the seed "cheap vps for developers" (10,955 total) and
"aws ec2 pricing" (1,045,293 total). Selected volume and cost-per-click:

| Keyword | Volume/mo | CPC |
|---|---|---|
| vps | 33,100 | $15.93 |
| vps server | 3,600 | $26.59 |
| cheap dedicated server | 1,300 | $12.48 |
| cloud vps | 1,000 | $21.63 |
| cheap servers | 880 | $6.95 |
| aws vps | 720 | $6.20 |
| amazon vps | 390 | $10.35 |
| vps aws | 320 | $12.51 |
| aws pricing | 2,900 | $6.47 |
| aws instance pricing | 720 | $4.85 |
| aws cost | 720 | $6.14 |
| aws cost explorer | 2,400 | $10.68 |
| aws secrets manager pricing | 1,000 | $22.12 |

A $15–26 CPC means cloud and VPS vendors bid aggressively for this traffic. That is the precondition
for referral revenue: the same advertisers run affiliate and referral programs, and a converted
reader is worth multiples of a display impression. It also means the head terms ("vps", "aws pricing")
are too competitive to win early — they are not the target.

## 2. The long tail is where a new site can win

Big-brand dominance on the head terms does not extend to the pattern this site generates.

**"m7i.large price"** (a per-instance query, exactly what `/instances/<type>.html` targets) — 126
results, top organic: `advisor.cloudzero.com`, `doit.com`, `aws.amazon.com`, `instances.vantage.sh`,
`costcalc.cloudoptimo.com`, `cloud.pump.co`.

All of those are FinOps or cloud-cost SaaS companies: independent evidence that per-instance pricing
queries carry commercial value worth building pages for. Note what none of them show: the spot price,
the reclaim risk, or yesterday's price. The daily diff is the differentiator.

**"cheapest 4 vcpu 16gb instance"** (the `/cheapest/<n>-vcpu-<n>gb.html` pattern) — 98 results, top
organic: `aws.amazon.com` (its own pricing page), `reddit.com` (a thread), `hetzner.com`,
`vultr.com`, `spendark.com/instances/`, `innoscale.net`.

Two of the six are small independent sites, and the query is answered in nested pages rather than on
a purpose-built page. That is a winnable shape.

**"aws instance pricing list"** — 112 results, top organic: `reddit.com` (rank 1), `finout.io`,
`aws.amazon.com`, `glassity.cloud`, `youtube.com`, `nops.io`. Rank 1 being a forum thread is a
market signal: the query is not satisfied by a canonical page, which is what `/instances.html` is
built to be.

## 3. What this implies for the build

1. **Target the pattern, not the head term.** 919 pages of instance/spec/region long tail beats one
   "aws pricing" page. Head terms are a year-2 goal.
2. **Freshness and spot data are the moat.** Competitors publish static per-instance pages. This site
   republishes daily with spot prices, reclaim risk, and a change log — content that is genuinely
   different tomorrow, which is also what makes return visits plausible.
3. **Commercial pages are separate from the value pages.** `/alternatives.html` and `/compare/*.html`
   carry the referral links; they are ranked by published prices, with the disclosure that
   accompanies every sponsored link.
4. **Reddit ranking first in this niche is an opportunity, not an accident.** The useful play is to
   be a genuinely better answer, and to participate in those threads with real data rather than
   drive-by links.
5. **Expect the timeline in [MONETIZATION.md](../MONETIZATION.md) to hold.** High CPC also means slow
   ranking: the numbers above support month 4–6 for first long-tail traction, not week 2.

## Re-running this

```bash
okou seo keyword-ideas "cheap vps for developers" --limit 60 --json > research/kw-cheap-vps.json
okou seo serp "m7i.large price" --json > research/serp-m7i.large-price.json
```
