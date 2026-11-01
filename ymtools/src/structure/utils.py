import math


def get_align16_count(ofs: int) -> int:
    return (-ofs) & 15


def get_align16_size(n: int) -> int:
    return math.ceil(n / 16) * 16


def sig_to_str(signature: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else f"\\x{c:02x}" for c in signature)
