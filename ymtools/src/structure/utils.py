def get_align16_count(ofs: int) -> int:
    return (-ofs) & 15
