#!/usr/bin/env python3
"""Tests for dependency manifest parsing and drift detection."""

import json
import unittest
from pathlib import Path
from unittest import mock

import check_dependencies


ROOT = Path(__file__).resolve().parents[1]


class DependencyAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = check_dependencies.load_manifest(ROOT / "dependencies.json")

    def test_current_pins_are_parsed(self):
        expected = {
            "uv": "0.8.14",
            "node": "22",
            "hyperframes": "0.7.82",
            "chrome-headless-shell": "148.0.7778.167",
            "puppeteer-browsers": "2.13.0",
            "playwright": "1.61.1",
            "kokoro": "0.9.4",
            "kokoro-model": "f3ff3571791e39611d31c381e3a41a3af07b4987",
            "actions-checkout": "5",
            "docker-setup-buildx-action": "3",
            "docker-login-action": "3",
            "docker-build-push-action": "6",
            "actions-upload-artifact": "4",
            "actions-download-artifact": "5",
            "docker-metadata-action": "5",
        }
        actual = {
            dependency["id"]: check_dependencies.extract_pin(ROOT, dependency)
            for dependency in self.manifest["dependencies"]
        }
        self.assertEqual(actual, expected)

    def test_audit_reports_drift_and_normalizes_action_major(self):
        latest = {
            dependency["id"]: check_dependencies.extract_pin(ROOT, dependency)
            for dependency in self.manifest["dependencies"]
        }
        latest["hyperframes"] = "99.0.0"
        latest["actions-checkout"] = "5.2.1"

        def fake_latest(source):
            dependency = next(
                item
                for item in self.manifest["dependencies"]
                if item["source"] is source
            )
            return latest[dependency["id"]]

        with mock.patch.object(
            check_dependencies, "resolve_latest", side_effect=fake_latest
        ):
            results = check_dependencies.audit(ROOT, self.manifest)
        statuses = {result["id"]: result["status"] for result in results}
        self.assertEqual(statuses["hyperframes"], "outdated")
        self.assertEqual(statuses["actions-checkout"], "current")
        self.assertEqual(
            sum(status == "current" for status in statuses.values()),
            len(statuses) - 1,
        )

    def test_manifest_is_valid_json(self):
        with (ROOT / "dependencies.json").open(encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
