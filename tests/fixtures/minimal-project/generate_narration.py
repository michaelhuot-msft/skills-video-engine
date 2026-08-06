"""Generate deterministic fixture narration and derive the composition timing."""

import json
from pathlib import Path

import numpy as np
import soundfile
from kokoro import KPipeline

PROJECT_ROOT = Path(__file__).resolve().parent
AUDIO_DIRECTORY = PROJECT_ROOT / "video" / "assets" / "audio"
TEMPLATE_PATH = PROJECT_ROOT / "video" / "index.template.txt"
COMPOSITION_PATH = PROJECT_ROOT / "video" / "index.html"
DURATIONS_PATH = PROJECT_ROOT / "durations.json"

SAMPLE_RATE_HZ = 24_000
VOICE = "af_heart"
SPEED = 1.1
TEXT = "A portable engine turns measured narration into deterministic video."


def main() -> None:
    """Synthesize narration, measure it, and write the derived timeline."""
    AUDIO_DIRECTORY.mkdir(parents=True, exist_ok=True)
    pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    chunks = [
        np.asarray(audio)
        for _graphemes, _phonemes, audio in pipeline(TEXT, voice=VOICE, speed=SPEED)
    ]
    if not chunks:
        raise RuntimeError("Kokoro produced no fixture audio")

    narration = np.concatenate(chunks)
    narration_path = AUDIO_DIRECTORY / "narration.wav"
    soundfile.write(narration_path, narration, SAMPLE_RATE_HZ)

    narration_seconds = len(narration) / SAMPLE_RATE_HZ
    narration_start = 0.25
    total_seconds = narration_start + narration_seconds + 0.5
    timing = {
        "voice": VOICE,
        "speed": SPEED,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "narration_seconds": narration_seconds,
        "narration_start_seconds": narration_start,
        "total_seconds": total_seconds,
    }
    DURATIONS_PATH.write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")

    composition = TEMPLATE_PATH.read_text(encoding="utf-8")
    replacements = {
        "__NARRATION_DURATION__": f"{narration_seconds:.3f}",
        "__NARRATION_START__": f"{narration_start:.3f}",
        "__TOTAL_DURATION__": f"{total_seconds:.3f}",
    }
    for marker, value in replacements.items():
        composition = composition.replace(marker, value)
    if any(marker in composition for marker in replacements):
        raise RuntimeError("Unresolved timing marker in fixture composition")
    COMPOSITION_PATH.write_text(composition, encoding="utf-8")

    print(f"narration: {narration_seconds:.3f}s")
    print(f"timeline: {total_seconds:.3f}s")


if __name__ == "__main__":
    main()
