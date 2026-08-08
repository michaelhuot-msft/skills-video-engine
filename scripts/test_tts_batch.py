"""Unit tests for the tts-batch orchestration logic (no model required)."""

import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import tts_batch


def valid_manifest(segments=None):
    return {
        "schema_version": 1,
        "defaults": {"voice": "af_heart", "speed": 1.1},
        "segments": segments
        or [
            {"id": "intro", "text": "First line."},
            {"id": "outro", "text": "Second line.", "voice": "af_bella", "speed": 0.9},
        ],
    }


def write_manifest(directory, payload):
    path = Path(directory) / "narration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_silence(path, frames, sample_rate=tts_batch.SAMPLE_RATE_HZ):
    with wave.open(str(path), "wb") as sink:
        sink.setnchannels(1)
        sink.setsampwidth(2)
        sink.setframerate(sample_rate)
        sink.writeframes(b"\x00\x00" * frames)


def make_fake_synthesizer(frames=2400, calls=None):
    def factory():
        def synthesize(segment, wav_path):
            if calls is not None:
                calls.append(segment["id"])
            write_silence(wav_path, frames)
            return frames

        return synthesize

    return factory


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_defaults_and_overrides_applied(self):
        path = write_manifest(self.root, valid_manifest())
        segments = tts_batch.load_manifest(path)
        self.assertEqual(segments[0]["voice"], "af_heart")
        self.assertEqual(segments[0]["speed"], 1.1)
        self.assertEqual(segments[0]["lang_code"], "a")
        self.assertEqual(segments[1]["voice"], "af_bella")
        self.assertEqual(segments[1]["speed"], 0.9)

    def test_rejects_missing_file(self):
        with self.assertRaises(tts_batch.ManifestError):
            tts_batch.load_manifest(self.root / "absent.json")

    def test_rejects_wrong_schema_version(self):
        payload = valid_manifest()
        payload["schema_version"] = 2
        path = write_manifest(self.root, payload)
        with self.assertRaises(tts_batch.ManifestError):
            tts_batch.load_manifest(path)

    def test_rejects_duplicate_ids(self):
        payload = valid_manifest(
            [{"id": "a", "text": "x"}, {"id": "a", "text": "y"}]
        )
        path = write_manifest(self.root, payload)
        with self.assertRaises(tts_batch.ManifestError):
            tts_batch.load_manifest(path)

    def test_rejects_unsafe_id(self):
        payload = valid_manifest([{"id": "../escape", "text": "x"}])
        path = write_manifest(self.root, payload)
        with self.assertRaises(tts_batch.ManifestError):
            tts_batch.load_manifest(path)

    def test_rejects_empty_text(self):
        payload = valid_manifest([{"id": "a", "text": "   "}])
        path = write_manifest(self.root, payload)
        with self.assertRaises(tts_batch.ManifestError):
            tts_batch.load_manifest(path)

    def test_rejects_boolean_speed(self):
        payload = valid_manifest([{"id": "a", "text": "x", "speed": True}])
        path = write_manifest(self.root, payload)
        with self.assertRaises(tts_batch.ManifestError):
            tts_batch.load_manifest(path)


class FingerprintTests(unittest.TestCase):
    def segment(self, **overrides):
        base = {
            "id": "intro",
            "text": "Hello.",
            "voice": "af_heart",
            "speed": 1.0,
            "lang_code": "a",
        }
        base.update(overrides)
        return base

    def test_stable_for_identical_settings(self):
        self.assertEqual(
            tts_batch.segment_fingerprint(self.segment()),
            tts_batch.segment_fingerprint(self.segment()),
        )

    def test_changes_when_content_changes(self):
        base = tts_batch.segment_fingerprint(self.segment())
        for overrides in (
            {"text": "Hello there."},
            {"voice": "af_bella"},
            {"speed": 1.2},
            {"lang_code": "b"},
        ):
            self.assertNotEqual(
                base, tts_batch.segment_fingerprint(self.segment(**overrides))
            )


class StateAndPlanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state_path = self.root / tts_batch.STATE_FILENAME

    def test_missing_and_corrupt_state_treated_as_empty(self):
        self.assertEqual(tts_batch.load_state(self.state_path), {})
        self.state_path.write_text("{not json", encoding="utf-8")
        self.assertEqual(tts_batch.load_state(self.state_path), {})

    def test_state_roundtrip_is_atomic(self):
        tts_batch.write_state(self.state_path, {"intro": {"frames": 10}})
        self.assertEqual(
            tts_batch.load_state(self.state_path), {"intro": {"frames": 10}}
        )
        self.assertFalse(
            self.state_path.with_name(self.state_path.name + ".tmp").exists()
        )

    def test_wav_frames_rejects_wrong_rate_and_missing_file(self):
        good = self.root / "good.wav"
        write_silence(good, 100)
        self.assertEqual(tts_batch.wav_frames(good), 100)
        wrong_rate = self.root / "wrong.wav"
        write_silence(wrong_rate, 100, sample_rate=22_050)
        self.assertIsNone(tts_batch.wav_frames(wrong_rate))
        self.assertIsNone(tts_batch.wav_frames(self.root / "absent.wav"))

    def test_plan_detects_stale_fingerprint_and_missing_audio(self):
        manifest_path = write_manifest(self.root, valid_manifest())
        segments = tts_batch.load_manifest(manifest_path)
        write_silence(self.root / "intro.wav", 50)
        state = {
            "intro": {
                "fingerprint": tts_batch.segment_fingerprint(segments[0]),
                "frames": 50,
            },
            "outro": {"fingerprint": "stale", "frames": 50},
        }
        complete, pending = tts_batch.plan_segments(segments, state, self.root)
        self.assertEqual([segment["id"] for segment in complete], ["intro"])
        self.assertEqual([segment["id"] for segment in pending], ["outro"])

    def test_plan_detects_frame_mismatch(self):
        manifest_path = write_manifest(self.root, valid_manifest())
        segments = tts_batch.load_manifest(manifest_path)
        write_silence(self.root / "intro.wav", 49)
        state = {
            "intro": {
                "fingerprint": tts_batch.segment_fingerprint(segments[0]),
                "frames": 50,
            }
        }
        _, pending = tts_batch.plan_segments(segments, state, self.root)
        self.assertIn("intro", [segment["id"] for segment in pending])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.manifest_path = write_manifest(self.root, valid_manifest())
        self.output_dir = self.root / "audio"

    def run_batch(self, calls=None, limit=None, dry_run=False, force=False):
        return tts_batch.run(
            self.manifest_path,
            self.output_dir,
            limit,
            dry_run,
            force,
            synthesizer_factory=make_fake_synthesizer(calls=calls),
        )

    def test_full_run_then_resume_skips_everything(self):
        calls = []
        self.assertEqual(self.run_batch(calls=calls), 0)
        self.assertEqual(calls, ["intro", "outro"])
        self.assertTrue((self.output_dir / "intro.wav").exists())
        self.assertTrue((self.output_dir / tts_batch.STATE_FILENAME).exists())
        self.assertEqual(self.run_batch(calls=calls), 0)
        self.assertEqual(calls, ["intro", "outro"])

    def test_limit_reports_pending_then_resume_completes(self):
        calls = []
        self.assertEqual(self.run_batch(calls=calls, limit=1), tts_batch.EXIT_PENDING)
        self.assertEqual(calls, ["intro"])
        self.assertFalse((self.output_dir / "outro.wav").exists())
        self.assertEqual(self.run_batch(calls=calls), 0)
        self.assertEqual(calls, ["intro", "outro"])

    def test_edited_segment_regenerates_only_that_segment(self):
        self.assertEqual(self.run_batch(), 0)
        payload = valid_manifest()
        payload["segments"][1]["text"] = "A different second line."
        write_manifest(self.root, payload)
        calls = []
        self.assertEqual(self.run_batch(calls=calls), 0)
        self.assertEqual(calls, ["outro"])

    def test_force_regenerates_everything(self):
        self.assertEqual(self.run_batch(), 0)
        calls = []
        self.assertEqual(self.run_batch(calls=calls, force=True), 0)
        self.assertEqual(calls, ["intro", "outro"])

    def test_dry_run_never_synthesizes_and_signals_pending(self):
        calls = []
        self.assertEqual(
            self.run_batch(calls=calls, dry_run=True), tts_batch.EXIT_PENDING
        )
        self.assertEqual(calls, [])
        self.assertEqual(self.run_batch(), 0)
        self.assertEqual(self.run_batch(dry_run=True), 0)

    def test_empty_synthesis_raises_and_cleans_temporary(self):
        def factory():
            def synthesize(segment, wav_path):
                write_silence(wav_path, 0)
                return 0

            return synthesize

        with self.assertRaises(RuntimeError):
            tts_batch.run(
                self.manifest_path,
                self.output_dir,
                None,
                False,
                False,
                synthesizer_factory=factory,
            )
        self.assertEqual(list(self.output_dir.glob("*.tmp")), [])
        self.assertFalse((self.output_dir / "intro.wav").exists())

    def test_state_records_duration_metadata(self):
        self.assertEqual(self.run_batch(), 0)
        state = tts_batch.load_state(self.output_dir / tts_batch.STATE_FILENAME)
        self.assertEqual(state["intro"]["frames"], 2400)
        self.assertEqual(state["intro"]["seconds"], 0.1)
        self.assertEqual(state["intro"]["path"], "intro.wav")


class MainTests(unittest.TestCase):
    def test_manifest_error_exits_one(self):
        self.assertEqual(tts_batch.main(["/nonexistent/manifest.json"]), 1)


if __name__ == "__main__":
    unittest.main()
