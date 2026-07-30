"""Pure logic for ModelDock: parsing, filtering, routing. No I/O, no network."""
import re

QUANT_RE = re.compile(r"(?<![A-Za-z0-9])(I?Q\d(?:_[A-Z0-9]+)*|F16|F32|BF16)(?![A-Za-z0-9])")


def parse_quant(name):
    m = QUANT_RE.search(name)
    if m:
        return m.group(1).upper()
    low = name.lower()
    if "8bit" in low or "8-bit" in low:
        return "MLX-8BIT"
    if "4bit" in low or "4-bit" in low:
        return "MLX-4BIT"
    return None


def quant_family(quant):
    if not quant:
        return None
    if quant.startswith("MLX"):
        return quant
    m = re.match(r"I?Q(\d)", quant)
    return "Q%s" % m.group(1) if m else quant


MOE_A_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)B-A(\d+(?:\.\d+)?)B(?![A-Za-z])")
MOE_X_RE = re.compile(r"(?i)(\d+)\s*x\s*(\d+(?:\.\d+)?)B(?![A-Za-z])")
PARAM_RE = re.compile(r"(?i)(?<![\dA-Za-z.])(\d+(?:\.\d+)?)B(?![A-Za-z])")

SIZE_BUCKETS = [("<=4B", 0, 4.5), ("7-9B", 4.5, 10), ("12-15B", 10, 16),
                ("20-35B", 16, 40), ("70B+", 40, float("inf"))]


def parse_params(name):
    m = MOE_A_RE.search(name)
    if m:
        return {"total_b": float(m.group(1)), "active_b": float(m.group(2)), "moe": True}
    m = MOE_X_RE.search(name)
    if m:
        n, per = int(m.group(1)), float(m.group(2))
        return {"total_b": n * per, "active_b": per, "moe": True}
    m = PARAM_RE.search(name)
    if m:
        return {"total_b": float(m.group(1)), "active_b": None, "moe": False}
    return None


def size_bucket(total_b):
    if total_b is None:
        return None
    for label, lo, hi in SIZE_BUCKETS:
        if lo <= total_b < hi:
            return label
    return None
