#!/usr/bin/env python3
"""Tests for dependency manifest parsing and drift detection."""

import io
import json
import os
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
            "uv": "0.12.1",
            "node": "24",
            "hyperframes": "0.7.82",
            "chrome-headless-shell": "148.0.7778.167",
            "puppeteer-browsers": "2.13.0",
            "playwright": "1.61.1",
            "kokoro": "0.9.4",
            "kokoro-model": "f3ff3571791e39611d31c381e3a41a3af07b4987",
            "kokoro-onnx": "0.5.0",
            "kokoro-onnx-model": "1.0",
            "actions-checkout": "7",
            "docker-setup-buildx-action": "4",
            "docker-login-action": "3",
            "docker-build-push-action": "7",
            "actions-upload-artifact": "4",
            "actions-download-artifact": "8",
            "docker-metadata-action": "6",
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
        latest["actions-checkout"] = "7.0.1"

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

    def test_github_request_uses_environment_token_as_bearer(self):
        token = "unit-test-token"
        response = io.BytesIO(b'{"tag_name": "v1.0.0"}')
        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": token}),
            mock.patch.object(
                check_dependencies.urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen,
        ):
            payload = check_dependencies.fetch_json(
                "https://api.github.com/repos/example/project/releases/latest"
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer " + token)
        self.assertEqual(payload, {"tag_name": "v1.0.0"})

    def test_fetch_json_bounds_retries_and_timeouts(self):
        error = check_dependencies.urllib.error.URLError("unavailable")
        with (
            mock.patch.object(
                check_dependencies.urllib.request,
                "urlopen",
                side_effect=error,
            ) as urlopen,
            mock.patch.object(check_dependencies.time, "sleep") as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, "after 2 attempts"):
                check_dependencies.fetch_json("https://example.com/versions.json")

        self.assertEqual(urlopen.call_count, check_dependencies.REQUEST_ATTEMPTS)
        self.assertEqual(
            [call.kwargs["timeout"] for call in urlopen.call_args_list],
            [check_dependencies.REQUEST_TIMEOUT_SECONDS] * 2,
        )
        sleep.assert_called_once_with(check_dependencies.RETRY_BACKOFF_SECONDS)


if __name__ == "__main__":
    unittest.main()
