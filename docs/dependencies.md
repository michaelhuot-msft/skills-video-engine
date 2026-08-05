# Dependency maintenance

`dependencies.json` is the source map for every version intentionally pinned in
the container and workflows. `scripts/check_dependencies.py` parses the real
files, queries documented upstream endpoints, and reports drift. It never edits
a pin.

The weekly dependency audit updates the single **Dependency audit findings**
issue. Dependabot separately proposes reviewable Docker and GitHub Actions
updates. Neither mechanism publishes an image.

## Check pins

```bash
python -m unittest discover -s scripts -p "test_*.py"
python scripts/check_dependencies.py
```

Exit status is `0` when current, `1` for drift, and `2` for malformed pins or
upstream lookup errors. Use `--allow-drift` only when collecting a report; it
does not hide lookup errors.

## Update a pin safely

1. Read the upstream release notes and security advisories. Confirm license,
   architecture, system-library, browser, and model compatibility.
2. Change the pin in its owning file. If a source or location changed, update
   `dependencies.json`. Update the expected value in
   `scripts/test_check_dependencies.py`.
3. Run the manifest tests and ShellCheck.
4. Build and smoke-test `linux/amd64` and `linux/arm64` natively. Do not replace
   either native CI job with emulation.
5. Verify the image still initializes Kokoro with `HF_HUB_OFFLINE=1`. The model
   revision must be a full commit SHA; never replace it with `main`.
6. Review the resulting image SBOM and size, then document noteworthy changes
   in the pull request. Publishing remains a separate tag/manual workflow.

Node major upgrades, browser/Playwright pairing, Kokoro package/model changes,
and any failed native build require human judgment. Agents must not merge a
dependency PR solely because a newer number exists.
