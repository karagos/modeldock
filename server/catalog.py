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
