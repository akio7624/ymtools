import logging

from ymtools.src.apkidx.structure.utils import get_align16_size
from ymtools.src.trp._tables import TRP_FILE_ENTRY, TRP_HEADER

__all__ = ["validate_header", "validate_entry_list"]
log = logging.getLogger(__name__)

HEADER_SIZE = 64
ENTRY_SIZE = 64


def validate_header(header: TRP_HEADER, entry_list: list[TRP_FILE_ENTRY]) -> list[str]:
    violations: list[str] = []
    if header.SIGNATURE != 0xDCA24D00:
        violations.append(f"HEADER.SIGNATURE must be 0xDCA24D00, current: 0x{header.SIGNATURE:08X}")
    if header.VERSION != 2:
        violations.append(f"HEADER.VERSION must be 2, current: {header.VERSION}")
    if header.ENTRY_SIZE != ENTRY_SIZE:
        violations.append(f"HEADER.ENTRY_SIZE must be {ENTRY_SIZE}, current: {header.ENTRY_SIZE}")
    if header.DEV_FLAG not in (0, 1):
        log.warning("Value of HEADER.DEV_FLAG may be 0 or 1, current: %s", header.DEV_FLAG)
    if len(entry_list) != header.FILE_COUNT:
        violations.append(f"Length of ENTRY_LIST must be {header.FILE_COUNT}, current: {len(entry_list)}")
    if any(header.PADDING):
        violations.append("All bytes of HEADER.PADDING must be 0")

    actual_file_size = header.actual_file_size  # property access is not narrowed by the type checker, so keep it in a local
    if actual_file_size is not None and actual_file_size != header.FILE_SIZE:
        violations.append(f"HEADER.FILE_SIZE must be {actual_file_size}, current: {header.FILE_SIZE}")
    actual_hash = header.actual_hash
    if actual_hash is not None and actual_hash != header.HASH:
        violations.append(f"HEADER.HASH must be {actual_hash.hex()}, current: {header.HASH.hex()}")
    return violations


def validate_entry_list(header: TRP_HEADER, entry_list: list[TRP_FILE_ENTRY]) -> list[str]:
    violations: list[str] = []

    # the files are placed in the order of the entries, each of them is aligned to 16 bytes
    expected_ofs = HEADER_SIZE + (ENTRY_SIZE * len(entry_list))
    names: set[bytes] = set()
    for i, entry in enumerate(entry_list):
        name_bytes = entry.FILE_NAME.split(b"\x00", 1)[0]
        if not name_bytes:
            violations.append(f"ENTRY_LIST[{i}].FILE_NAME must not be empty")
        else:
            try:
                name_bytes.decode("utf-8")
            except UnicodeDecodeError:
                violations.append(f"ENTRY_LIST[{i}].FILE_NAME must be a utf-8 string")
            if b"/" in name_bytes or b"\\" in name_bytes:
                violations.append(f"ENTRY_LIST[{i}].FILE_NAME must not contain a path separator, current: '{entry.name}'")
            if name_bytes in names:
                violations.append(f"ENTRY_LIST[{i}].FILE_NAME is duplicated: '{entry.name}'")
            names.add(name_bytes)
        if any(entry.FILE_NAME[len(name_bytes) + 1:]):
            violations.append(f"All bytes of ENTRY_LIST[{i}].FILE_NAME after the null terminator must be 0")

        if any(entry.unknown_1):
            log.warning("Value of ENTRY_LIST[%d].unknown_1 may be all 0", i)
        if entry.unknown_2 != 0:
            log.warning("Value of ENTRY_LIST[%d].unknown_2 may be 0, current: %s", i, entry.unknown_2)
        if entry.unknown_3 not in (0, 1):
            log.warning("Value of ENTRY_LIST[%d].unknown_3 may be 0 or 1, current: %s", i, entry.unknown_3)
        if any(entry.PADDING):
            violations.append(f"All bytes of ENTRY_LIST[{i}].PADDING must be 0")

        if entry.START_OFS != expected_ofs:
            violations.append(f"ENTRY_LIST[{i}].START_OFS must be {expected_ofs}, current: {entry.START_OFS}")
        expected_ofs = entry.START_OFS + get_align16_size(entry.FILE_SIZE)

    if expected_ofs != header.FILE_SIZE:
        violations.append(f"The end of the last file must be {header.FILE_SIZE}, current: {expected_ofs}")
    return violations
