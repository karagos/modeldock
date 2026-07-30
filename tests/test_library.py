import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import library


def touch(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)


class TestLibrary(unittest.TestCase):
    def test_missing_destination(self):
        out = library.scan("/nonexistent/path/xyz")
        self.assertFalse(out["connected"])

    def test_scan(self):
        with tempfile.TemporaryDirectory() as d:
            touch(os.path.join(d, "Models/llm/Qwen/Qwen3-14B-GGUF/q.Q4_K_M.gguf"), 100)
            touch(os.path.join(d, "Models/llm/Qwen/Qwen3-14B-GGUF/q.Q8_0.gguf"), 200)
            touch(os.path.join(d, "Models/comfyui/loras/style.safetensors"), 50)
            out = library.scan(d)
            self.assertTrue(out["connected"])
            self.assertEqual(len(out["text_models"]), 1)
            m = out["text_models"][0]
            self.assertEqual(m["company"], "Qwen")
            self.assertEqual(m["size"], 300)
            self.assertEqual(sorted(m["quants"]), ["Q4_K_M", "Q8_0"])
            self.assertEqual(out["comfy_models"][0]["subfolder"], "loras")
            self.assertEqual(out["total_bytes"], 350)

    def test_part_files_marked_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            touch(os.path.join(d, "Models/llm/X/M/model.gguf.part"), 10)
            out = library.scan(d)
            self.assertTrue(out["text_models"][0]["incomplete"])


if __name__ == "__main__":
    unittest.main()
