import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import catalog


class TestQuant(unittest.TestCase):
    def test_parse_common_quants(self):
        self.assertEqual(catalog.parse_quant("Llama-3-8B.Q4_K_M.gguf"), "Q4_K_M")
        self.assertEqual(catalog.parse_quant("model-IQ4_XS.gguf"), "IQ4_XS")
        self.assertEqual(catalog.parse_quant("m-Q8_0.gguf"), "Q8_0")
        self.assertEqual(catalog.parse_quant("weights-F16.gguf"), "F16")

    def test_qwen_name_not_a_quant(self):
        self.assertIsNone(catalog.parse_quant("Qwen3-Instruct.gguf"))

    def test_mlx_bits(self):
        self.assertEqual(catalog.parse_quant("mlx-community/Qwen3-14B-4bit"), "MLX-4BIT")
        self.assertEqual(catalog.parse_quant("Model-8bit"), "MLX-8BIT")

    def test_family(self):
        self.assertEqual(catalog.quant_family("Q4_K_M"), "Q4")
        self.assertEqual(catalog.quant_family("IQ4_XS"), "Q4")
        self.assertEqual(catalog.quant_family("F16"), "F16")
        self.assertEqual(catalog.quant_family("MLX-4BIT"), "MLX-4BIT")
        self.assertIsNone(catalog.quant_family(None))


class TestParams(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(catalog.parse_params("Meta-Llama-3.1-8B-Instruct"),
                         {"total_b": 8.0, "active_b": None, "moe": False})
        self.assertEqual(catalog.parse_params("Qwen3-0.6B")["total_b"], 0.6)

    def test_moe_a_form(self):
        p = catalog.parse_params("Qwen3-30B-A3B-GGUF")
        self.assertEqual((p["total_b"], p["active_b"], p["moe"]), (30.0, 3.0, True))

    def test_moe_x_form(self):
        p = catalog.parse_params("Mixtral-8x7B-v0.1")
        self.assertEqual((p["total_b"], p["active_b"], p["moe"]), (56.0, 7.0, True))

    def test_none(self):
        self.assertIsNone(catalog.parse_params("Phi-model"))

    def test_buckets(self):
        self.assertEqual(catalog.size_bucket(0.6), "<=4B")
        self.assertEqual(catalog.size_bucket(8), "7-9B")
        self.assertEqual(catalog.size_bucket(14), "12-15B")
        self.assertEqual(catalog.size_bucket(30), "20-35B")
        self.assertEqual(catalog.size_bucket(70), "70B+")
        self.assertIsNone(catalog.size_bucket(None))


class TestCapabilities(unittest.TestCase):
    def test_detect(self):
        self.assertIn("vision", catalog.detect_capabilities("org/Qwen2.5-VL-7B", ["image-text-to-text"]))
        self.assertIn("thinking", catalog.detect_capabilities("org/DeepSeek-R1-Distill", []))
        self.assertIn("thinking", catalog.detect_capabilities("org/QwQ-32B", []))
        self.assertIn("coding", catalog.detect_capabilities("org/Qwen2.5-Coder-14B", []))
        self.assertIn("agentic", catalog.detect_capabilities("org/x", ["function-calling"]))

    def test_search_params_text(self):
        p = catalog.build_search_params(q="qwen", mtype="gguf", company="Qwen",
                                        capabilities=["thinking"], sort="downloads")
        self.assertEqual(p["filter"], "gguf")
        self.assertEqual(p["author"], "Qwen")
        self.assertIn("reasoning", p["search"])
        self.assertEqual(p["sort"], "downloads")

    def test_search_params_multi_capability(self):
        p = catalog.build_search_params(q="", mtype="gguf", company="",
                                        capabilities=["thinking", "vision"], sort="downloads")
        self.assertEqual(p["pipeline_tag"], "image-text-to-text")  # vision
        self.assertIn("reasoning", p["search"])                    # thinking, combined

    def test_search_params_image(self):
        p = catalog.build_search_params(q="", mtype="image", company="",
                                        capabilities=["video-gen"], sort="trending")
        self.assertEqual(p["pipeline_tag"], "text-to-video")
        self.assertEqual(p["sort"], "trendingScore")

    def test_search_params_mlx(self):
        p = catalog.build_search_params(q="llama", mtype="mlx", company="",
                                        capabilities=[], sort="newest")
        self.assertEqual(p["filter"], "mlx")
        self.assertEqual(p["sort"], "lastModified")

    def test_moe_is_not_a_query_param(self):
        p = catalog.build_search_params(q="", mtype="gguf", company="",
                                        capabilities=["moe", "coding"], sort="downloads")
        self.assertIn("coder", p.get("search", ""))
        self.assertNotIn("moe", p.get("search", ""))  # moe is a post-filter, not a term


class TestRoutingAndFits(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(catalog.sanitize_component("meta-llama/Llama:3"), "meta-llama_Llama_3")
        self.assertEqual(catalog.sanitize_component("  .. "), "untitled")

    def test_comfy_routing(self):
        self.assertEqual(catalog.comfy_subfolder("lora", [], "style.safetensors"), "loras")
        self.assertEqual(catalog.comfy_subfolder("", [], "wan_vae.safetensors"), "vae")
        self.assertEqual(catalog.comfy_subfolder("upscaler", [], "x4-esrgan.safetensors"), "upscale_models")
        self.assertEqual(catalog.comfy_subfolder("image-gen", [], "flux1-dev.safetensors"), "checkpoints")

    def test_fits(self):
        gib = 1024 ** 3
        self.assertEqual(catalog.fits_badge(10 * gib, 32 * gib), "green")
        self.assertEqual(catalog.fits_badge(22 * gib, 32 * gib), "orange")
        self.assertEqual(catalog.fits_badge(30 * gib, 32 * gib), "red")
        self.assertEqual(catalog.fits_badge(10 * gib, 0), "unknown")

    def test_split_grouping(self):
        files = [
            {"path": "m-Q4_K_M-00001-of-00002.gguf", "size": 10, "sha256": "a"},
            {"path": "m-Q4_K_M-00002-of-00002.gguf", "size": 7, "sha256": "b"},
            {"path": "m-Q8_0.gguf", "size": 30, "sha256": "c"},
        ]
        groups = catalog.group_gguf_files(files)
        self.assertEqual(len(groups), 2)
        multi = next(g for g in groups if len(g["files"]) == 2)
        self.assertEqual(multi["size"], 17)
        self.assertEqual(multi["quant"], "Q4_K_M")
        self.assertIn("2 parts", multi["label"])


class TestMlxBitsExtended(unittest.TestCase):
    def test_6bit_and_3bit(self):
        self.assertEqual(catalog.parse_quant("mlx-community/Qwen3-14B-6bit"), "MLX-6BIT")
        self.assertEqual(catalog.parse_quant("Model-3bit"), "MLX-3BIT")


class TestMergeCards(unittest.TestCase):
    C = [{"id": "a/x", "downloads": 100, "updated": "2026-01-01"},
         {"id": "b/y", "downloads": 300, "updated": "2026-03-01"}]
    D = [{"id": "c/z", "downloads": 200, "updated": "2026-02-01"},
         {"id": "a/x", "downloads": 100, "updated": "2026-01-01"}]  # duplicate id

    def test_dedupe_and_downloads_sort(self):
        out = catalog.merge_cards([self.C, self.D], "downloads")
        self.assertEqual([m["id"] for m in out], ["b/y", "c/z", "a/x"])

    def test_newest_sort(self):
        out = catalog.merge_cards([self.C, self.D], "newest")
        self.assertEqual(out[0]["id"], "b/y")
        self.assertEqual(out[1]["id"], "c/z")

    def test_trending_interleaves(self):
        out = catalog.merge_cards([self.C, self.D], "trending")
        self.assertEqual([m["id"] for m in out], ["a/x", "c/z", "b/y"])


class TestReadmeExcerpt(unittest.TestCase):
    MD = ("---\nlicense: apache-2.0\ntags: [gguf]\n---\n"
          "# Qwen3 14B\n\n"
          "Qwen3-14B is a **strong** general model with [thinking](https://x.y) mode.\n\n"
          "```python\nimport nothing\n```\n"
          "| table | row |\n"
          "It supports 100+ languages.\n")

    def test_strips_noise_keeps_prose(self):
        out = catalog.readme_excerpt(self.MD)
        self.assertIn("Qwen3-14B is a strong general model with thinking mode.", out)
        self.assertIn("100+ languages", out)
        self.assertNotIn("license", out)
        self.assertNotIn("#", out)
        self.assertNotIn("|", out)
        self.assertNotIn("import", out)

    def test_limit_and_empty(self):
        self.assertEqual(catalog.readme_excerpt(""), "")
        long = catalog.readme_excerpt("word " * 400, limit=50)
        self.assertLessEqual(len(long), 52)
        self.assertTrue(long.endswith("…"))


class TestCapFamilies(unittest.TestCase):
    def test_membership(self):
        self.assertIn("thinking", catalog.TEXT_CAPS)
        self.assertIn("lora", catalog.IMAGE_CAPS)
        self.assertNotIn("thinking", catalog.IMAGE_CAPS)


if __name__ == "__main__":
    unittest.main()
