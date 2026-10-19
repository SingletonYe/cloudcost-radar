#!/usr/bin/env python3
"""Regression tests for the CloudCost Radar pipeline. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import fetch_data  # noqa: E402
import site_base  # noqa: E402

RAW_ROW = {
    "InstanceType": "m7i.large", "Memory": "8 GiB", "VCPUS": 2, "Storage": "EBS only",
    "Network": "Up to 12.5 Gigabit", "Cost": 0.1008, "MonthlyPrice": 73.584, "GPU": None,
    "SpotPrice": "0.0449", "SpotReclaimRate": "15-20%", "SpotSavingRate": "61%",
    "Reserved1yPrice": "0.0667", "Reserved3yPrice": "0.0457",
    "Reserved1yConveritblePrice": "0.0741", "Reserved3yConveritblePrice": "0.0511",
}


class TestNormalisation(unittest.TestCase):
    def test_valid_row_is_parsed(self):
        row = fetch_data.normalize_row(RAW_ROW)
        assert row is not None
        self.assertEqual(row["type"], "m7i.large")
        self.assertEqual(row["family"], "m7i")
        self.assertEqual(row["vcpu"], 2)
        self.assertEqual(row["mem_gb"], 8.0)
        self.assertAlmostEqual(row["od_hour"], 0.1008)
        self.assertAlmostEqual(row["spot_hour"], 0.0449)
        self.assertAlmostEqual(row["r1y_hour"], 0.0667)

    def test_rejects_missing_and_absurd_values(self):
        self.assertIsNone(fetch_data.normalize_row({}))
        self.assertIsNone(fetch_data.normalize_row({**RAW_ROW, "Cost": 0}))
        self.assertIsNone(fetch_data.normalize_row({**RAW_ROW, "Cost": -1}))
        self.assertIsNone(fetch_data.normalize_row({**RAW_ROW, "VCPUS": 0}))
        self.assertIsNone(fetch_data.normalize_row({**RAW_ROW, "Memory": ""}))

    def test_implausible_spot_is_dropped_not_invented(self):
        row = fetch_data.normalize_row({**RAW_ROW, "SpotPrice": "9.99"})
        assert row is not None
        self.assertIsNone(row["spot_hour"], "a spot price far above on-demand must be discarded")

    def test_monthly_is_recomputed_when_inconsistent(self):
        row = fetch_data.normalize_row({**RAW_ROW, "MonthlyPrice": 1.0})
        assert row is not None
        self.assertAlmostEqual(row["od_month"], round(0.1008 * 730, 3))

    def test_memory_units(self):
        self.assertEqual(fetch_data.to_memory_gb("0.5 GiB"), 0.5)
        self.assertEqual(fetch_data.to_memory_gb("1,952 GiB"), 1952.0)
        self.assertEqual(fetch_data.to_memory_gb("2 TiB"), 2048.0)
        self.assertEqual(fetch_data.to_memory_gb("512 MiB"), 0.5)

    def test_price_strings(self):
        self.assertEqual(fetch_data.to_float("$1,234.50"), 1234.5)
        self.assertIsNone(fetch_data.to_float(""))
        self.assertIsNone(fetch_data.to_float("unavailable"))

    def test_watchlist(self):
        self.assertTrue(fetch_data.is_watchlisted("m7i.large"))
        self.assertFalse(fetch_data.is_watchlisted("m7i.24xlarge"))
        self.assertFalse(fetch_data.is_watchlisted("nonsense"))


class TestRendering(unittest.TestCase):
    def test_escape(self):
        self.assertEqual(site_base.esc("<b>&'\"x"), "&lt;b&gt;&amp;&#x27;&quot;x")

    def test_table_wraps_cells(self):
        """Regression: cells must be wrapped in td, otherwise tables render as run-on text."""
        builder = site_base.Builder(ROOT / "site")
        html = builder.table([("Instance", False), ("Price", True)], [["m7i.large", "$0.10"]])
        self.assertIn("<td class=\"\">m7i.large</td>", html)
        self.assertIn("<td class=\"num\">$0.10</td>", html)

    def test_table_sort_keys(self):
        builder = site_base.Builder(ROOT / "site")
        html = builder.table([("Instance", False, "type"), ("Price", True, "od")],
                             [["x", "1"]], table_id="t")
        self.assertIn('data-key="type"', html)
        self.assertIn('data-key="od"', html)


class TestBuildArtefacts(unittest.TestCase):
    """End-to-end: build from the committed data and check the bundle is publishable."""

    def test_build_and_qa_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "site"
            build = subprocess.run([sys.executable, str(ROOT / "src" / "build_site.py"),
                                    "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertTrue((out / "index.html").exists())
            self.assertTrue((out / "sitemap.xml").exists())
            self.assertTrue((out / "instances" / "m7i.large.html").exists())
            qa = subprocess.run([sys.executable, str(ROOT / "src" / "qa_check.py"),
                                 "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(qa.returncode, 0, qa.stdout + qa.stderr)
            self.assertIn("PASS", qa.stdout)

    def test_data_asset_shape(self):
        doc = json.loads((ROOT / "data" / "latest" / "instances.json").read_text())
        builder = site_base.Builder(ROOT / "site")
        payload = builder.build_data_asset()
        self.assertEqual(len(payload["instances"]), len(doc["instances"]))
        self.assertEqual(len(payload["instances"][0]), 8)

    def test_no_guessed_provider_prices(self):
        """A provider whose price was not verified must carry a null price, not a number."""
        catalog = json.loads((ROOT / "config" / "alternatives.json").read_text())
        for prov in catalog["providers"]:
            for plan in prov["plans"]:
                if plan["price_status"] != "verified":
                    self.assertIsNone(plan["price_usd_month"],
                                      f"{prov['id']} {plan['id']} must not carry an unverified price")
                else:
                    self.assertIsNotNone(plan.get("verified_at"),
                                         f"{prov['id']} {plan['id']} verified price needs a date")


if __name__ == "__main__":
    unittest.main()
