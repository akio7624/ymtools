import logging

from ymtools.src.structure._tables import ENDILTLE, GENEEOF, GENESTRT, PACKFSLS, PACKHEDR, PACKTOC
from ymtools.src.structure.exceptions import ValidationException
from ymtools.src.structure.utils import get_align16_size, sig_to_str

__all__ = [
    "validate_endiltle", "validate_packhedr", "validate_packtoc", "validate_toc_order",
    "validate_packfsls", "validate_genestrt", "validate_geneeof", "raise_if_invalid",
]
log = logging.getLogger(__name__)


def validate_endiltle(endiltle: ENDILTLE, name: str) -> list[str]:
    violations: list[str] = []
    if endiltle.SIGNATURE != b"ENDILTLE":
        violations.append(f"{name}.SIGNATURE must be 'ENDILTLE', current: '{sig_to_str(endiltle.SIGNATURE)}'")
    else:
        if endiltle.TABLE_SIZE != 0:
            violations.append(f"Size of {name} table must be 0, current: {endiltle.TABLE_SIZE}")
    return violations


def validate_packhedr(packhedr: PACKHEDR, name: str, expected_name_idx: int) -> list[str]:
    violations: list[str] = []
    if packhedr.SIGNATURE != b"PACKHEDR":
        violations.append(f"{name}.SIGNATURE must be 'PACKHEDR', current: '{sig_to_str(packhedr.SIGNATURE)}'")
    else:
        if packhedr.TABLE_SIZE != 32:
            violations.append(f"Size of {name} table must be 32, current: {packhedr.TABLE_SIZE}")
        if packhedr.unknown_1 != 65536:
            violations.append(f"Value of {name}.unknown_1 must be 65536, current: {packhedr.unknown_1}")
        if packhedr.NAME_IDX != expected_name_idx:
            log.warning(f"Value of {name}.NAME_IDX may be {expected_name_idx}, current: {packhedr.NAME_IDX}")
        if packhedr.FS_PAD_TYPE not in [1, 2]:
            violations.append(f"Value of {name}.FS_PAD_TYPE may be 1 or 2, current: {packhedr.FS_PAD_TYPE}")
    return violations


def validate_packtoc(packtoc: PACKTOC) -> list[str]:
    violations: list[str] = []
    if packtoc.SIGNATURE != b"PACKTOC ":
        violations.append(f"PACKTOC.SIGNATURE must be 'PACKTOC ', current: '{sig_to_str(packtoc.SIGNATURE)}'")
    else:
        expected_table_size = get_align16_size(4 + 4 + 4 + 4 + (packtoc.TOC_SEG_SIZE * packtoc.TOC_SEG_COUNT))
        if packtoc.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of PACKTOC table must be {expected_table_size}, current: {packtoc.TABLE_SIZE}")
        if packtoc.TOC_SEG_SIZE != 40:
            violations.append(f"Size of PACKTOC.TOC_SEG_SIZE must be 40, current: {packtoc.TOC_SEG_SIZE}")
        if packtoc.TOC_SEG_LIST_OFS != 16:
            violations.append(f"Offset of PACKTOC.TOC_SEG_LIST_OFS must be 16, current: {packtoc.TOC_SEG_LIST_OFS}")
        if packtoc.unknown_1 != 0:
            log.warning(f"Value of PACKTOC.unknown_1 may be 0")
        if len(packtoc.TOC_SEG_LIST) != packtoc.TOC_SEG_COUNT:
            violations.append(f"Length of PACKTOC.TOC_SEG_LIST must be {packtoc.TOC_SEG_COUNT}, current: {len(packtoc.TOC_SEG_LIST)}")
    return violations


def validate_toc_order(packtoc: PACKTOC, genestrt: GENESTRT) -> list[str]:
    violations: list[str] = []
    segs = packtoc.TOC_SEG_LIST
    strings = genestrt.STRING_LIST

    for i, seg in enumerate(segs):
        if seg.IDENTIFIER != 1 or seg.ENTRY_COUNT < 2:  # only directories with 2+ children
            continue
        children = segs[seg.ENTRY_INDEX: seg.ENTRY_INDEX + seg.ENTRY_COUNT]
        if any(c.NAME_IDX >= len(strings) for c in children):  # reported by the TOC_SEGMENT validator
            continue
        names = [strings[c.NAME_IDX].encode("utf-8") for c in children]
        if any(a >= b for a, b in zip(names, names[1:])):
            violations.append(f"Children of TOC_SEG_LIST[{i}] are not sorted by name")
    return violations


def validate_packfsls(packfsls: PACKFSLS) -> list[str]:
    violations: list[str] = []
    if packfsls.SIGNATURE != b"PACKFSLS":
        violations.append(f"PACKFSLS.SIGNATURE must be 'PACKFSLS', current: '{sig_to_str(packfsls.SIGNATURE)}'")
    else:
        expected_table_size = get_align16_size(4 + 4 + 4 + 4 + (packfsls.FS_SEG_SIZE * packfsls.FS_SEG_COUNT))
        if packfsls.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of PACKFSLS table must be {expected_table_size}, current: {packfsls.TABLE_SIZE}")
        if packfsls.FS_SEG_SIZE != 40:
            violations.append(f"Size of PACKFSLS.FS_SEG_SIZE must be 40, current: {packfsls.FS_SEG_SIZE}")
        if packfsls.FS_SEG_LIST_OFS != 16:
            violations.append(f"Offset of PACKFSLS.FS_SEG_LIST_OFS must be 16, current: {packfsls.FS_SEG_LIST_OFS}")
        if packfsls.unknown_1 != 0:
            log.warning("Value of PACKFSLS.unknown_1 may be 0")
        if len(packfsls.FS_SEG_LIST) != packfsls.FS_SEG_COUNT:
            violations.append(f"Length of PACKFSLS.FS_SEG_LIST must be {packfsls.FS_SEG_COUNT}, current: {len(packfsls.FS_SEG_LIST)}")
    return violations


def validate_genestrt(genestrt: GENESTRT, name: str) -> list[str]:
    violations: list[str] = []
    if genestrt.SIGNATURE != b"GENESTRT":
        violations.append(f"{name}.SIGNATURE must be 'GENESTRT', current: '{sig_to_str(genestrt.SIGNATURE)}'")
    else:
        string_list_size = sum(len(s.encode("utf-8")) + 1 for s in genestrt.STRING_LIST)  # +1 for null
        string_list_ofs = get_align16_size(4 + 4 + 4 + 4 + (4 * genestrt.STRING_COUNT))
        expected_table_size = get_align16_size(string_list_ofs + string_list_size)

        if genestrt.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of {name} table must be {expected_table_size}, current: {genestrt.TABLE_SIZE}")
        if genestrt.STRING_OFS_LIST_OFS != 16:
            violations.append(f"Offset of {name}.STRING_OFS_LIST_OFS must be 16, current: {genestrt.STRING_OFS_LIST_OFS}")
        if genestrt.STRING_LIST_OFS != string_list_ofs:
            violations.append(f"Offset of {name}.STRING_LIST_OFS must be {string_list_ofs}, current: {genestrt.STRING_LIST_OFS}")
        if genestrt.TABLE_SIZE_2 != genestrt.TABLE_SIZE:
            log.warning("Value of %s.TABLE_SIZE_2 may be equal to TABLE_SIZE(%d), current: %d", name, genestrt.TABLE_SIZE, genestrt.TABLE_SIZE_2)
        if len(genestrt.STRING_OFS_LIST) != genestrt.STRING_COUNT:
            violations.append(f"Length of {name}.STRING_OFS_LIST must be {genestrt.STRING_COUNT}, current: {len(genestrt.STRING_OFS_LIST)}")
        if any(genestrt.STRING_OFS_LIST_PAD):
            violations.append(f"All bytes of {name}.STRING_OFS_LIST_PAD must be 0")
        if len(genestrt.STRING_LIST) != genestrt.STRING_COUNT:
            violations.append(f"Length of {name}.STRING_LIST must be {genestrt.STRING_COUNT}, current: {len(genestrt.STRING_LIST)}")
        if any(genestrt.STRING_LIST_PAD):
            violations.append(f"All bytes of {name}.STRING_LIST_PAD must be 0")
    return violations


def validate_geneeof(geneeof: GENEEOF, name: str) -> list[str]:
    violations: list[str] = []
    if geneeof.SIGNATURE != b"GENEEOF ":
        violations.append(f"{name}.SIGNATURE must be 'GENEEOF ', current: '{sig_to_str(geneeof.SIGNATURE)}'")
    else:
        if geneeof.TABLE_SIZE != 0:
            violations.append(f"Size of {name} table must be 0, current: {geneeof.TABLE_SIZE}")
    return violations


def raise_if_invalid(violations: list[str], exception: type[ValidationException]) -> None:
    if violations:
        log.error(f"{exception.LABEL} validation failed: {len(violations)} violation(s)")
        for v in violations:
            log.error(f"  {v}")
        raise exception(violations)
    log.info(f"{exception.LABEL} validation PASS!")
