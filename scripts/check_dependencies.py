#!/usr/bin/env python3
"""Audit pinned engine dependencies without modifying repository files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REQUEST_ATTEMPTS = 2
REQUEST_TIMEOUT_SECONDS = 10
RETRY_BACKOFF_SECONDS = 1


def load_manifest(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    if manifest.get("schema_version") != 1:
        raise ValueError("dependencies.json must use schema_version 1")
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("dependencies.json must contain dependencies")
    identifiers = [dependency.get("id") for dependency in dependencies]
    if any(not identifier for identifier in identifiers):
        raise ValueError("every dependency must have an id")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("dependency ids must be unique")
    return manifest


def extract_pin(root: Path, dependency: dict[str, Any]) -> str:
    values: list[str] = []
    for pin in dependency["pins"]:
        path = root / pin["file"]
        content = path.read_text(encoding="utf-8")
        matches = re.findall(pin["pattern"], content, flags=re.MULTILINE)
        if not matches:
            raise ValueError(
                f"{dependency['id']}: no pin found in {pin['file']}"
            )
        for value in matches:
            if isinstance(value, tuple):
                value = value[0]
            values.append(value)
    if len(set(values)) != 1:
        raise ValueError(f"{dependency['id']}: pin locations disagree: {values}")
    return values[0]


def fetch_json(url: str) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "skills-video-engine-dependency-audit",
    }
    github_token = os.environ.get("GITHUB_TOKEN")
    if "api.github.com" in url and github_token:
        headers["Authorization"] = "Bearer " + github_token
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    last_error: OSError | urllib.error.URLError | None = None
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError) as error:
            last_error = error
            if attempt < REQUEST_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS)
    raise RuntimeError(
        f"upstream request failed after {REQUEST_ATTEMPTS} attempts: {last_error}"
    )


def resolve_latest(source: dict[str, Any]) -> str:
    payload = fetch_json(source["url"])
    if source["type"] == "node_latest_lts":
        release = next(item for item in payload if item.get("lts"))
        latest = release["version"]
    elif source["type"] == "json":
        latest = payload
        for component in source["path"]:
            latest = latest[component]
    else:
        raise ValueError(f"unsupported source type: {source['type']}")
    latest = str(latest)
    prefix = source.get("strip_prefix", "")
    if prefix and latest.startswith(prefix):
        latest = latest[len(prefix) :]
    return latest


def comparable(version: str, comparison: str) -> str:
    if comparison == "major":
        return version.removeprefix("v").split(".", maxsplit=1)[0]
    if comparison == "exact":
        return version.removeprefix("v")
    raise ValueError(f"unsupported comparison: {comparison}")


def audit(root: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
    results = []
    for dependency in manifest["dependencies"]:
        result = {
            "id": dependency["id"],
            "name": dependency["name"],
            "current": "",
            "latest": "",
            "status": "",
            "source": dependency["source"]["release_url"],
            "error": "",
        }
        try:
            result["current"] = extract_pin(root, dependency)
            result["latest"] = resolve_latest(dependency["source"])
            comparison = dependency.get("comparison", "exact")
            result["status"] = (
                "current"
                if comparable(result["current"], comparison)
                == comparable(result["latest"], comparison)
                else "outdated"
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            ValueError,
            urllib.error.URLError,
        ) as error:
            result["status"] = "error"
            result["error"] = str(error)
        results.append(result)
    return results


def summarize(results: list[dict[str, str]]) -> dict[str, int]:
    return {
        status: sum(result["status"] == status for result in results)
        for status in ("current", "outdated", "error")
    }


def markdown_report(results: list[dict[str, str]]) -> str:
    summary = summarize(results)
    lines = [
        "# Dependency audit",
        "",
        (
            f"**{summary['outdated']} outdated, {summary['error']} errors, "
            f"{summary['current']} current.**"
        ),
        "",
        "| Dependency | Pinned | Latest | Status | Upstream |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        latest = result["latest"] or "unknown"
        lines.append(
            f"| {result['name']} | `{result['current'] or 'unknown'}` | "
            f"`{latest}` | {result['status']} | [source]({result['source']}) |"
        )
        if result["error"]:
            lines.append(
                f"| ↳ check error |  |  | `{result['error']}` |  |"
            )
    lines.extend(
        [
            "",
            "## Update procedure",
            "",
            "Review upstream release notes and follow "
            "[docs/dependencies.md]"
            "(https://github.com/mhuot/skills-video-engine/blob/main/"
            "docs/dependencies.md). "
            "Never update pins without rebuilding and smoke-testing both "
            "native architectures.",
            "",
            "_This report is generated from `dependencies.json`; no pins were changed._",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("dependencies.json")
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--allow-drift",
        action="store_true",
        help="exit successfully when outdated pins are found",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(args.manifest)
    results = audit(args.root, manifest)
    summary = summarize(results)
    payload = {"summary": summary, "dependencies": results}
    rendered = (
        json.dumps(payload, indent=2) + "\n"
        if args.format == "json"
        else markdown_report(results)
    )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    if args.json_output:
        args.json_output.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    if summary["error"]:
        return 2
    if summary["outdated"] and not args.allow_drift:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
