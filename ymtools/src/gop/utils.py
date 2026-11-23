from dataclasses import dataclass

from ymtools.src.gop._tables import GOP_GDAT, GOP_GMET, GOP_GREC, GREC_COLUMN
from ymtools.src.gop.column_types import COLUMN_TYPES, decode_cell, decode_unknown_cell


@dataclass(slots=True)
class MetaNode:
    name: str
    items: list["str | MetaNode"]  # a value or a child node


def get_column_sizes(column_list: list[GREC_COLUMN], record_size: int) -> list[int]:
    # the size of an unknown type is the distance to the next column, or to the end of the record
    offsets = sorted({col.OFFSET for col in column_list})
    sizes: list[int] = []
    for col in column_list:
        col_type = COLUMN_TYPES.get(col.TYPE)
        if col_type is not None:
            sizes.append(col_type.SIZE)
        else:
            sizes.append(next((ofs for ofs in offsets if ofs > col.OFFSET), record_size) - col.OFFSET)
    return sizes


def build_meta_tree(gmet: GOP_GMET, string_list: list[str]) -> MetaNode:
    nodes = iter(gmet.NODE_LIST)

    def build(node) -> MetaNode:
        items: list[str | MetaNode] = []
        for item in node.ITEM_LIST:
            items.append(string_list[item.VALUE] if item.KIND == 0 else build(next(nodes)))
        return MetaNode(name=string_list[node.NAME_IDX], items=items)

    return build(next(nodes))


def read_rows(grec: GOP_GREC, gdat: GOP_GDAT, string_list: list[str]) -> list[list[object]]:
    sizes = get_column_sizes(grec.COLUMN_LIST, gdat.RECORD_SIZE)
    rows: list[list[object]] = []
    for record in gdat.RECORD_LIST:
        row: list[object] = []
        for col, size in zip(grec.COLUMN_LIST, sizes):
            raw = record[col.OFFSET:col.OFFSET + size]
            col_type = COLUMN_TYPES.get(col.TYPE)
            row.append(decode_unknown_cell(raw) if col_type is None else decode_cell(col_type, raw, string_list))
        rows.append(row)
    return rows
