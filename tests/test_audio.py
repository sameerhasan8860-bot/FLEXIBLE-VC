import unittest
import numpy as np

from audio import AudioProcessor


class AudioProcessorTests(unittest.TestCase):
    def test_process_preserves_pcm_frame_length(self):
        processor = AudioProcessor()
        samples = np.array([0, 1000, -1000, 32767, -32768, 200], dtype=np.int16)
        output = processor.process(samples.tobytes())
        self.assertEqual(len(output), len(samples.tobytes()))
        decoded = np.frombuffer(output, dtype=np.int16)
        self.assertTrue(np.all(decoded >= -32768))
        self.assertTrue(np.all(decoded <= 32767))

    def test_numeric_values_are_safely_clamped(self):
        processor = AudioProcessor()
        self.assertEqual(processor.update("db", 999), 96.0)
        self.assertEqual(processor.update("gain", 999), 512.0)
        self.assertEqual(processor.update("bass", -999), -48.0)
        self.assertEqual(processor.update("echo", 999), 100.0)

    def test_level_combines_all_effects_and_higher_values_are_stronger(self):
        processor = AudioProcessor()
        low = processor.update("level", 100)
        profile_100 = dict(processor.settings)
        high = processor.update("level", 1000)
        profile_1000 = dict(processor.settings)
        self.assertEqual(low, 100.0)
        self.assertEqual(high, 1000.0)
        for name in ("db", "gain", "bass", "treble", "echo", "distortion"):
            self.assertGreater(profile_100[name], 0)
            self.assertGreater(profile_1000[name], profile_100[name])

    def test_level_accepts_large_finite_values_and_rejects_invalid_values(self):
        processor = AudioProcessor()
        self.assertEqual(processor.update("level", 1e100), 1e100)
        with self.assertRaises(ValueError):
            processor.update("level", -1)
        with self.assertRaises(ValueError):
            processor.update("level", float("inf"))

    def test_invalid_values_are_rejected(self):
        processor = AudioProcessor()
        with self.assertRaises(ValueError):
            processor.update("gain", float("inf"))
        with self.assertRaises(ValueError):
            processor.update("unknown", 1.0)


if __name__ == "__main__":
    unittest.main()
