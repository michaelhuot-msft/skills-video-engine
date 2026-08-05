#!/usr/bin/env bash
set -euo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"

report_json="${1:-dependency-report.json}"
report_markdown="${2:-dependency-report.md}"
title="Dependency audit findings"

issue_data="$(
  gh issue list \
    --repo "${GITHUB_REPOSITORY}" \
    --state all \
    --search "\"${title}\" in:title" \
    --json number,state,title \
    --jq ".[] | select(.title == \"${title}\") | [.number, .state] | @tsv" |
    head -1
)"
IFS=$'\t' read -r issue_number issue_state <<< "${issue_data}"
findings="$(jq '.summary.outdated + .summary.error' "${report_json}")"

if [ "${findings}" -gt 0 ]; then
  if [ -n "${issue_number}" ]; then
    gh issue edit "${issue_number}" \
      --repo "${GITHUB_REPOSITORY}" \
      --body-file "${report_markdown}"
    if [ "${issue_state}" = "CLOSED" ]; then
      gh issue reopen "${issue_number}" --repo "${GITHUB_REPOSITORY}"
    fi
  else
    gh issue create \
      --repo "${GITHUB_REPOSITORY}" \
      --title "${title}" \
      --body-file "${report_markdown}"
  fi
elif [ -n "${issue_number}" ]; then
  gh issue edit "${issue_number}" \
    --repo "${GITHUB_REPOSITORY}" \
    --body-file "${report_markdown}"
  if [ "${issue_state}" = "OPEN" ]; then
    gh issue close "${issue_number}" \
      --repo "${GITHUB_REPOSITORY}" \
      --comment "All tracked dependency pins are current."
  fi
fi
