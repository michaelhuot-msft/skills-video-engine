#!/usr/bin/env python3
"""Resumable, memory-bounded batch narration generation for mounted projects.

Reads a project-owned narration manifest, synthesizes one segment at a time
with Kokoro, and streams each segment straight to a PCM16 WAV file so no more
than one audio chunk is held in memory. Progress is checkpointed to a state
file after every segment, so an interrupted or memory-killed run resumes where
it stopped. Segments are fingerprinted over their text and voice settings;
editing a segment regenerates only that segment.

Exit codes: 0 when every segment is complete, 10 when segments remain pending
(for example after --limit or --dry-run), and 1 on invalid input.
"""

from __future__ import annotations

import argparse
import gc
import json
import re
import sys
import wave
from pathlib import Path
from typing import Any, Callable

MANIFEST_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1
STATE_FILENAME = "tts-state.json"
SAMPLE_RATE_HZ = 24_000
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_LANG_CODE = "a"
SEGMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXIT_PENDING = 10

Synthesizer = Callable[[dict[str, Any], Path], int]


class ManifestError(ValueError):
    """Raised when the narration manifest is missing or invalid."""


def _fail(message: str) -> ManifestError:
    return ManifestError(f"narration manifest: {message}")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    """Load and normalize manifest segments, applying manifest defaults."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise _fail(f"{path} does not exist") from error
    except json.JSONDecodeError as error:
        raise _fail(f"{path} is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise _fail("top level must be an object")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise _fail(f"schema_version must be {MANIFEST_SCHEMA_VERSION}")

    defaults = payload.get("defaults", {})
    if not isinstance(defaults, dict):
        raise _fail("defaults must be an object")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise _fail("segments must be a non-empty list")

    segments = []
    seen_ids = set()
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            raise _fail(f"segment {index} must be an object")
        segment = normalize_segment(raw, defaults, index)
        if segment["id"] in seen_ids:
            raise _fail(f"duplicate segment id {segment['id']!r}")
        seen_ids.add(segment["id"])
        segments.append(segment)
    return segments


def normalize_segment(
    raw: dict[str, Any], defaults: dict[str, Any], index: int
) -> dict[str, Any]:
    """Validate one manifest segment and fill in defaulted voice settings."""
    segment_id = raw.get("id")
    if not isinstance(segment_id, str) or not SEGMENT_ID_PATTERN.match(segment_id):
        raise _fail(
            f"segment {index} id must match {SEGMENT_ID_PATTERN.pattern}"
        )
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _fail(f"segment {segment_id!r} text must be a non-empty string")
    voice = raw.get("voice", defaults.get("voice", DEFAULT_VOICE))
    if not isinstance(voice, str) or not voice:
        raise _fail(f"segment {segment_id!r} voice must be a non-empty string")
    speed = raw.get("speed", defaults.get("speed", DEFAULT_SPEED))
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or speed <= 0:
        raise _fail(f"segment {segment_id!r} speed must be a positive number")
    lang_code = raw.get("lang_code", defaults.get("lang_code", DEFAULT_LANG_CODE))
    if not isinstance(lang_code, str) or not lang_code:
        raise _fail(f"segment {segment_id!r} lang_code must be a non-empty string")
    return {
        "id": segment_id,
        "text": text.strip(),
        "voice": voice,
        "speed": float(speed),
        "lang_code": lang_code,
    }


def segment_fingerprint(segment: dict[str, Any]) -> str:
    """Hash the fields that determine a segment's audio content."""
    import hashlib

    material = json.dumps(
        {
            "text": segment["text"],
            "voice": segment["voice"],
            "speed": segment["speed"],
            "lang_code": segment["lang_code"],
            "sample_rate_hz": SAMPLE_RATE_HZ,
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    """Load resume state, treating a missing or corrupt file as empty."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != STATE_SCHEMA_VERSION
        or not isinstance(payload.get("segments"), dict)
    ):
        return {}
    return payload["segments"]


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON via a temp file and rename so readers never see a partial file."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_state(path: Path, segments: dict[str, Any]) -> None:
    """Persist resume state atomically."""
    write_json_atomic(
        path,
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "segments": segments,
        },
    )


def wav_frames(path: Path) -> int | None:
    """Return the frame count of a PCM WAV file, or None if unreadable."""
    try:
        with wave.open(str(path), "rb") as source:
            if source.getframerate() != SAMPLE_RATE_HZ:
                return None
            return source.getnframes()
    except (FileNotFoundError, wave.Error, EOFError):
        return None


def segment_is_complete(
    segment: dict[str, Any], state: dict[str, Any], output_dir: Path
) -> bool:
    """Check whether a segment's recorded output still matches the manifest."""
    entry = state.get(segment["id"])
    if not isinstance(entry, dict):
        return False
    if entry.get("fingerprint") != segment_fingerprint(segment):
        return False
    frames = wav_frames(output_dir / f"{segment['id']}.wav")
    return frames is not None and frames == entry.get("frames") and frames > 0


def plan_segments(
    segments: list[dict[str, Any]], state: dict[str, Any], output_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split manifest segments into (complete, pending) lists."""
    complete = []
    pending = []
    for segment in segments:
        if segment_is_complete(segment, state, output_dir):
            complete.append(segment)
        else:
            pending.append(segment)
    return complete, pending


def make_kokoro_synthesizer() -> Synthesizer:
    """Build the Kokoro-backed synthesizer, importing heavy deps lazily."""
    from kokoro import KPipeline

    pipelines: dict[str, Any] = {}

    def synthesize(segment: dict[str, Any], wav_path: Path) -> int:
        import numpy as np

        lang_code = segment["lang_code"]
        if lang_code not in pipelines:
            pipelines[lang_code] = KPipeline(
                lang_code=lang_code, repo_id="hexgrad/Kokoro-82M"
            )
        pipeline = pipelines[lang_code]
        frames = 0
        with wave.open(str(wav_path), "wb") as sink:
            sink.setnchannels(1)
            sink.setsampwidth(2)
            sink.setframerate(SAMPLE_RATE_HZ)
            for _graphemes, _phonemes, audio in pipeline(
                segment["text"], voice=segment["voice"], speed=segment["speed"]
            ):
                chunk = np.asarray(audio, dtype=np.float32)
                pcm = (np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2")
                sink.writeframes(pcm.tobytes())
                frames += len(pcm)
                del audio, chunk, pcm
        return frames

    return synthesize


def generate_pending(
    pending: list[dict[str, Any]],
    state: dict[str, Any],
    output_dir: Path,
    state_path: Path,
    limit: int | None,
    synthesizer_factory: Callable[[], Synthesizer],
) -> int:
    """Generate up to `limit` pending segments, checkpointing after each one."""
    synthesize = synthesizer_factory()
    batch = pending if limit is None else pending[:limit]
    for position, segment in enumerate(batch, start=1):
        wav_path = output_dir / f"{segment['id']}.wav"
        temporary_path = wav_path.with_name(wav_path.name + ".tmp")
        frames = synthesize(segment, temporary_path)
        if frames <= 0:
            temporary_path.unlink(missing_ok=True)
            raise RuntimeError(f"segment {segment['id']!r} produced no audio")
        temporary_path.replace(wav_path)
        state[segment["id"]] = {
            "fingerprint": segment_fingerprint(segment),
            "frames": frames,
            "seconds": round(frames / SAMPLE_RATE_HZ, 3),
            "voice": segment["voice"],
            "speed": segment["speed"],
            "path": wav_path.name,
        }
        write_state(state_path, state)
        gc.collect()
        print(
            f"[{position}/{len(batch)}] {segment['id']}: "
            f"{frames / SAMPLE_RATE_HZ:.3f}s generated"
        )
    return len(batch)


def run(
    manifest_path: Path,
    output_dir: Path,
    limit: int | None,
    dry_run: bool,
    force: bool,
    synthesizer_factory: Callable[[], Synthesizer] = make_kokoro_synthesizer,
) -> int:
    """Execute one batch pass and return the process exit code."""
    segments = load_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / STATE_FILENAME
    state = load_state(state_path)
    if force:
        complete, pending = [], list(segments)
    else:
        complete, pending = plan_segments(segments, state, output_dir)

    if dry_run:
        for segment in complete:
            print(f"complete: {segment['id']}")
        for segment in pending:
            print(f"pending:  {segment['id']}")
        print(f"skipped: {len(complete)}, pending: {len(pending)}")
        return 0 if not pending else EXIT_PENDING

    generated = 0
    if pending:
        generated = generate_pending(
            pending, state, output_dir, state_path, limit, synthesizer_factory
        )
    remaining = len(pending) - generated
    print(
        f"skipped: {len(complete)}, generated: {generated}, remaining: {remaining}"
    )
    return EXIT_PENDING if remaining else 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the batch."""
    parser = argparse.ArgumentParser(
        prog="tts-batch",
        description=(
            "Generate narration segments from a manifest, one at a time, "
            "resuming completed work across runs."
        ),
    )
    parser.add_argument("manifest", type=Path, help="narration manifest JSON path")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="segment output directory (default: <manifest dir>/narration-audio)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="generate at most N segments this run, then exit 10 if work remains",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report segment status without loading the model or generating",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate every segment even if its recorded output matches",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    output_dir = (
        args.output_dir
        if args.output_dir is not None
        else args.manifest.resolve().parent / "narration-audio"
    )
    try:
        return run(args.manifest, output_dir, args.limit, args.dry_run, args.force)
    except ManifestError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
