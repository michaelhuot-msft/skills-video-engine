# Agent instructions

## Dependency pins

- Treat `dependencies.json` as the auditable source map and the Dockerfile or
  workflow reference as the authoritative pin.
- Run `python -m unittest discover -s scripts -p "test_*.py"` before and after
  editing any pin.
- Follow `docs/dependencies.md`; inspect upstream release notes instead of
  blindly accepting Dependabot or dependency-audit findings.
- Preserve the cached Kokoro model and offline runtime. Keep the model on a full
  commit SHA.
- Preserve native Linux AMD64 and ARM64 CI. Both image builds and smoke tests
  must pass before a pin update is ready.
- Never make the audit script mutate files or publish images.

## Runtime contract

- Keep `/project` as the default working directory and preserve the documented
  tool names on `PATH`.
- Runtime commands must work without network access after the image is pulled.
- Do not require root. Arbitrary numeric UIDs must be able to initialize
  Kokoro and Chromium and write mounted-project outputs.
- Run `bash scripts/e2e_test.sh <image>` for any Dockerfile or runtime change.
  The fixture must remain small, deterministic, and free of committed media.
