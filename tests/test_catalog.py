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


if __name__ == "__main__":
    unittest.main()
