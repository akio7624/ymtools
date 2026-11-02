import math
from pathlib import Path

from ymtools.src.structure._tables import TOC_SEGMENT


def get_align16_count(ofs: int) -> int:
    return (-ofs) & 15


def get_align16_size(n: int) -> int:
    return math.ceil(n / 16) * 16


def sig_to_str(signature: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else f"\\x{c:02x}" for c in signature)


def _split_path(path: str) -> list[str]:
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"'..' is not allowed in the path '{path}'")
    return parts


def resolve_apk_path(idx_dir: Path, base: Path | None, recorded: str) -> Path:
    if base is not None and base.drive:
        raise ValueError(f"base must not have a drive: '{base}'")
    base_parts = _split_path(base.as_posix()) if base is not None else []
    parts = _split_path(recorded)
    if not parts:
        raise ValueError("The recorded path of the apk is empty")
    dir_parts, name = parts[:-1], parts[-1]

    # number of leading folders shared by base and the recorded path
    common = 0
    while common < min(len(base_parts), len(dir_parts)) and base_parts[common] == dir_parts[common]:
        common += 1

    ups = len(base_parts) - common  # levels to go up from the idx folder
    real = idx_dir.resolve()
    if ups > len(real.parts) - 1:
        raise ValueError(f"Cannot go up {ups} level(s) from '{real}' for the recorded path '{recorded}' with base '{base}'")
    for _ in range(ups):
        real = real.parent
    return real.joinpath(*dir_parts[common:], name)


def walk_toc(toc_seg_list: list[TOC_SEGMENT], string_list: list[str]) -> tuple[list[str | None], list[int]]:
    paths: list[str | None] = [None] * len(toc_seg_list)
    order: list[int] = []
    if not toc_seg_list:
        return paths, order

    paths[0] = ""
    stack = [0]
    while stack:
        i = stack.pop()
        if i != 0:
            order.append(i)
        seg = toc_seg_list[i]
        if seg.IDENTIFIER != 1:
            continue

        children: list[int] = []
        for c in range(seg.ENTRY_INDEX, seg.ENTRY_INDEX + seg.ENTRY_COUNT):
            if c >= len(toc_seg_list) or paths[c] is not None:  # out of range, or already visited
                continue
            name = string_list[toc_seg_list[c].NAME_IDX]
            paths[c] = f"{paths[i]}/{name}" if paths[i] else name
            children.append(c)
        stack.extend(reversed(children))
    return paths, order
