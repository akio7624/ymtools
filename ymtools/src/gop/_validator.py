import logging
import struct

from ymtools.src.apkidx.structure._tables import GENESTRT
from ymtools.src.apkidx.structure.utils import get_align16_size, sig_to_str
from ymtools.src.gop._tables import GOP_GDAT, GOP_GFIN, GOP_GMET, GOP_GREC
from ymtools.src.gop.column_types import COLUMN_TYPES, KIND_BOOL, KIND_STRING
from ymtools.src.gop.utils import get_column_sizes

__all__ = ["validate_gfin", "validate_gmet", "validate_grec", "validate_genestrt", "validate_gdat"]
log = logging.getLogger(__name__)


def validate_gfin(gfin: GOP_GFIN) -> list[str]:
    violations: list[str] = []
    if gfin.SIGNATURE != b"GOP GFIN":
        violations.append(f"GFIN.SIGNATURE must be 'GOP GFIN', current: '{sig_to_str(gfin.SIGNATURE)}'")
    else:
        if gfin.TABLE_SIZE != 16:
            violations.append(f"Size of GFIN table must be 16, current: {gfin.TABLE_SIZE}")
        if gfin.VERSION != 2:
            violations.append(f"Value of GFIN.VERSION must be 2, current: {gfin.VERSION}")
        if gfin.unknown_1 != 1:
            log.warning("Value of GFIN.unknown_1 may be 1, current: %s", gfin.unknown_1)
        if gfin.unknown_2 != 0:
            log.warning("Value of GFIN.unknown_2 may be 0, current: %s", gfin.unknown_2)
        if gfin.unknown_3 != 0:
            log.warning("Value of GFIN.unknown_3 may be 0, current: %s", gfin.unknown_3)
    return violations


def validate_gmet(gmet: GOP_GMET, genestrt: GENESTRT) -> list[str]:
    violations: list[str] = []
    if gmet.SIGNATURE != b"GOP GMET":
        violations.append(f"GMET.SIGNATURE must be 'GOP GMET', current: '{sig_to_str(gmet.SIGNATURE)}'")
    else:
        nodes = gmet.NODE_LIST
        string_count = len(genestrt.STRING_LIST)

        # offset of each node from the start of the table body
        node_ofs: list[int] = []
        ofs = 0
        for node in nodes:
            node_ofs.append(ofs)
            ofs += 4 + (4 * len(node.ITEM_LIST))

        expected_table_size = get_align16_size(ofs)
        if gmet.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of GMET table must be {expected_table_size}, current: {gmet.TABLE_SIZE}")

        # the children follow their parent in DFS order
        last = 0

        def check_children(i: int) -> None:
            nonlocal last
            for j, item in enumerate(nodes[i].ITEM_LIST):
                if item.KIND == 1:
                    last += 1
                    if item.VALUE != node_ofs[last]:
                        violations.append(f"GMET.NODE_LIST[{i}].ITEM_LIST[{j}].VALUE must be {node_ofs[last]}, current: {item.VALUE}")
                    check_children(last)

        for i, node in enumerate(nodes):
            if node.NAME_IDX >= string_count:
                violations.append(f"GMET.NODE_LIST[{i}].NAME_IDX must be less than {string_count}, current: {node.NAME_IDX}")
            if len(node.ITEM_LIST) != node.ITEM_COUNT:
                violations.append(f"Length of GMET.NODE_LIST[{i}].ITEM_LIST must be {node.ITEM_COUNT}, current: {len(node.ITEM_LIST)}")
            for j, item in enumerate(node.ITEM_LIST):
                if item.KIND not in [0, 1]:
                    violations.append(f"GMET.NODE_LIST[{i}].ITEM_LIST[{j}].KIND must be 0 or 1, current: {item.KIND}")
                elif item.KIND == 0 and item.VALUE >= string_count:
                    violations.append(f"GMET.NODE_LIST[{i}].ITEM_LIST[{j}].VALUE must be less than {string_count}, current: {item.VALUE}")
        if nodes:
            check_children(0)
    return violations


def validate_grec(grec: GOP_GREC, genestrt: GENESTRT) -> list[str]:
    violations: list[str] = []
    if grec.SIGNATURE != b"GOP GREC":
        violations.append(f"GREC.SIGNATURE must be 'GOP GREC', current: '{sig_to_str(grec.SIGNATURE)}'")
    else:
        string_count = len(genestrt.STRING_LIST)
        expected_table_size = get_align16_size(4 + (12 * grec.COLUMN_COUNT))
        if grec.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of GREC table must be {expected_table_size}, current: {grec.TABLE_SIZE}")
        if len(grec.COLUMN_LIST) != grec.COLUMN_COUNT:
            violations.append(f"Length of GREC.COLUMN_LIST must be {grec.COLUMN_COUNT}, current: {len(grec.COLUMN_LIST)}")

        for i, col in enumerate(grec.COLUMN_LIST):
            if col.TYPE > 31:
                violations.append(f"GREC.COLUMN_LIST[{i}].TYPE must be less than 32, current: {col.TYPE}")
            elif col.TYPE not in COLUMN_TYPES:
                log.warning("GREC.COLUMN_LIST[%d].TYPE %s is an unknown type", i, col.TYPE)
            if col.NAME_IDX >= string_count:
                violations.append(f"GREC.COLUMN_LIST[{i}].NAME_IDX must be less than {string_count}, current: {col.NAME_IDX}")
            if col.LANG_FLAG not in [0, 1]:
                violations.append(f"GREC.COLUMN_LIST[{i}].LANG_FLAG must be 0 or 1, current: {col.LANG_FLAG}")

        # the first column is the SelfId of the record
        if len(grec.COLUMN_LIST) == 0:
            violations.append("GREC.COLUMN_LIST must have the SelfId column as the first column")
        else:
            first = grec.COLUMN_LIST[0]
            if first.TYPE != 14:
                violations.append(f"GREC.COLUMN_LIST[0].TYPE must be 14(RecId), current: {first.TYPE}")
            if first.OFFSET != 0:
                violations.append(f"GREC.COLUMN_LIST[0].OFFSET must be 0, current: {first.OFFSET}")
    return violations


def validate_genestrt(genestrt: GENESTRT, name: str) -> list[str]:
    violations: list[str] = []
    if genestrt.SIGNATURE != b"GENESTRT":
        violations.append(f"{name}.SIGNATURE must be 'GENESTRT', current: '{sig_to_str(genestrt.SIGNATURE)}'")
    else:
        string_list_size = sum(len(s.encode("utf-8")) + 1 for s in genestrt.STRING_LIST)  # +1 for null
        string_list_ofs = get_align16_size(4 + 4 + 4 + 4 + (4 * (genestrt.STRING_COUNT + 1)))
        expected_table_size = get_align16_size(string_list_ofs + string_list_size)

        if genestrt.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of {name} table must be {expected_table_size}, current: {genestrt.TABLE_SIZE}")
        if genestrt.STRING_OFS_LIST_OFS != 16:
            violations.append(f"Offset of {name}.STRING_OFS_LIST_OFS must be 16, current: {genestrt.STRING_OFS_LIST_OFS}")
        if genestrt.STRING_LIST_OFS != string_list_ofs:
            violations.append(f"Offset of {name}.STRING_LIST_OFS must be {string_list_ofs}, current: {genestrt.STRING_LIST_OFS}")
        if genestrt.TABLE_SIZE_2 != genestrt.TABLE_SIZE:
            log.warning("Value of %s.TABLE_SIZE_2 may be equal to TABLE_SIZE(%d), current: %d", name, genestrt.TABLE_SIZE, genestrt.TABLE_SIZE_2)
        if len(genestrt.STRING_OFS_LIST) != genestrt.STRING_COUNT + 1:
            violations.append(f"Length of {name}.STRING_OFS_LIST must be {genestrt.STRING_COUNT + 1}, current: {len(genestrt.STRING_OFS_LIST)}")
        if any(genestrt.STRING_OFS_LIST_PAD):
            violations.append(f"All bytes of {name}.STRING_OFS_LIST_PAD must be 0")
        if len(genestrt.STRING_LIST) != genestrt.STRING_COUNT:
            violations.append(f"Length of {name}.STRING_LIST must be {genestrt.STRING_COUNT}, current: {len(genestrt.STRING_LIST)}")
        if any(genestrt.STRING_LIST_PAD):
            violations.append(f"All bytes of {name}.STRING_LIST_PAD must be 0")

        # the last element of STRING_OFS_LIST is the size of STRING_LIST
        ofs = 0
        for i, s in enumerate(genestrt.STRING_LIST):
            if i < len(genestrt.STRING_OFS_LIST) and genestrt.STRING_OFS_LIST[i] != ofs:
                violations.append(f"{name}.STRING_OFS_LIST[{i}] must be {ofs}, current: {genestrt.STRING_OFS_LIST[i]}")
            ofs += len(s.encode("utf-8")) + 1
        if len(genestrt.STRING_OFS_LIST) == genestrt.STRING_COUNT + 1 and genestrt.STRING_OFS_LIST[-1] != ofs:
            violations.append(f"{name}.STRING_OFS_LIST[{genestrt.STRING_COUNT}] must be {ofs}, current: {genestrt.STRING_OFS_LIST[-1]}")
    return violations


def validate_gdat(gdat: GOP_GDAT, grec: GOP_GREC, genestrt: GENESTRT) -> list[str]:
    violations: list[str] = []
    if gdat.SIGNATURE != b"GOP GDAT":
        violations.append(f"GDAT.SIGNATURE must be 'GOP GDAT', current: '{sig_to_str(gdat.SIGNATURE)}'")
    else:
        string_count = len(genestrt.STRING_LIST)
        record_list_ofs = get_align16_size(4 + 4 + 4 + 4 + (4 * gdat.RECORD_COUNT))
        expected_table_size = get_align16_size(record_list_ofs + (gdat.RECORD_SIZE * gdat.RECORD_COUNT))

        if gdat.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of GDAT table must be {expected_table_size}, current: {gdat.TABLE_SIZE}")
        if gdat.RECORD_SIZE % 4 != 0:
            violations.append(f"GDAT.RECORD_SIZE must be a multiple of 4, current: {gdat.RECORD_SIZE}")
        if gdat.INDEX_LIST_OFS != 16:
            violations.append(f"Offset of GDAT.INDEX_LIST_OFS must be 16, current: {gdat.INDEX_LIST_OFS}")
        if gdat.RECORD_LIST_OFS != record_list_ofs:
            violations.append(f"Offset of GDAT.RECORD_LIST_OFS must be {record_list_ofs}, current: {gdat.RECORD_LIST_OFS}")
        if len(gdat.INDEX_LIST) != gdat.RECORD_COUNT:
            violations.append(f"Length of GDAT.INDEX_LIST must be {gdat.RECORD_COUNT}, current: {len(gdat.INDEX_LIST)}")
        if any(gdat.INDEX_LIST_PAD):
            violations.append("All bytes of GDAT.INDEX_LIST_PAD must be 0")
        if len(gdat.RECORD_LIST) != gdat.RECORD_COUNT:
            violations.append(f"Length of GDAT.RECORD_LIST must be {gdat.RECORD_COUNT}, current: {len(gdat.RECORD_LIST)}")
        if any(gdat.GDAT_PAD):
            violations.append("All bytes of GDAT.GDAT_PAD must be 0")

        # columns must fit in the record. the cells are checked only if they do
        columns = grec.COLUMN_LIST
        sizes = get_column_sizes(columns, gdat.RECORD_SIZE)
        fit = True
        for i, (col, size) in enumerate(zip(columns, sizes)):
            if size <= 0 or col.OFFSET + size > gdat.RECORD_SIZE:
                violations.append(f"GREC.COLUMN_LIST[{i}] (offset: {col.OFFSET}, size: {size}) is out of the record, RECORD_SIZE: {gdat.RECORD_SIZE}")
                fit = False
        if not fit or len(gdat.RECORD_LIST) != gdat.RECORD_COUNT:
            return violations

        for i, col in enumerate(columns):
            col_type = COLUMN_TYPES.get(col.TYPE)
            if col_type is None or col_type.KIND not in (KIND_STRING, KIND_BOOL):
                continue
            for r, record in enumerate(gdat.RECORD_LIST):
                value = struct.unpack_from("<i", record, col.OFFSET)[0] if col_type.KIND == KIND_STRING else record[col.OFFSET]
                if col_type.KIND == KIND_STRING and value >= string_count:
                    violations.append(f"GDAT.RECORD_LIST[{r}] value of GREC.COLUMN_LIST[{i}] must be less than {string_count}, current: {value}")
                elif col_type.KIND == KIND_BOOL and value not in [0, 1]:
                    violations.append(f"GDAT.RECORD_LIST[{r}] value of GREC.COLUMN_LIST[{i}] must be 0 or 1, current: {value}")

        # INDEX_LIST is the row numbers sorted by the SelfId
        if columns and columns[0].TYPE == 14 and columns[0].OFFSET == 0:
            self_id_idx = [struct.unpack_from("<I", record, 0)[0] for record in gdat.RECORD_LIST]
            if any(idx >= string_count for idx in self_id_idx):
                violations.append("SelfId of the records must not be null")
                return violations

            self_ids = [genestrt.STRING_LIST[idx].encode("utf-8") for idx in self_id_idx]
            if len(set(self_ids)) != len(self_ids):
                violations.append("SelfId of the records must not be duplicated")
            if sorted(gdat.INDEX_LIST) != list(range(gdat.RECORD_COUNT)):
                violations.append("GDAT.INDEX_LIST must contain every row number exactly once")
            else:
                ordered = [self_ids[i] for i in gdat.INDEX_LIST]
                if any(a > b for a, b in zip(ordered, ordered[1:])):
                    violations.append("GDAT.INDEX_LIST must be sorted by the SelfId of the records")
    return violations
