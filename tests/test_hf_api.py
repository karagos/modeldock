import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import hf_api


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener(payload):
    calls = []

    def opener(req, timeout=0):
        calls.append(req.full_url)
        return FakeResponse(json.dumps(payload).encode())
    opener.calls = calls
    return opener


class TestHfApi(unittest.TestCase):
    def test_search_url_and_parse(self):
        op = fake_opener([{"id": "Qwen/Qwen3-14B-GGUF", "downloads": 5, "likes": 2,
                           "tags": ["gguf"], "lastModified": "2026-01-01T00:00:00Z"}])
        out = hf_api.search_models({"filter": "gguf", "search": "qwen"}, opener=op)
        self.assertEqual(out[0]["id"], "Qwen/Qwen3-14B-GGUF")
        self.assertIn("api/models?", op.calls[0])
        self.assertIn("filter=gguf", op.calls[0])

    def test_tree_normalizes_lfs(self):
        op = fake_opener([
            {"type": "file", "path": "m-Q4_K_M.gguf", "size": 99,
             "lfs": {"oid": "abc", "size": 99}},
            {"type": "file", "path": "README.md", "size": 5},
            {"type": "directory", "path": "assets"},
        ])
        files = hf_api.model_tree("org/repo", opener=op)
        self.assertEqual(files, [{"path": "m-Q4_K_M.gguf", "size": 99, "sha256": "abc"},
                                 {"path": "README.md", "size": 5, "sha256": None}])
        self.assertIn("/api/models/org/repo/tree/main?recursive=true", op.calls[0])

    def test_file_url_quotes(self):
        self.assertEqual(hf_api.file_url("org/repo", "a b.gguf"),
                         "https://huggingface.co/org/repo/resolve/main/a%20b.gguf")


if __name__ == "__main__":
    unittest.main()
