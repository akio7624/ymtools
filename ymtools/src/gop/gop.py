import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.gop._reader import parse_genestrt, parse_gdat, parse_gfin, parse_gmet, parse_grec, read_table
from ymtools.src.gop._tables import GENESTRT, GMET_NODE, GOP_GDAT, GOP_GFIN, GOP_GMET, GOP_GREC, GREC_COLUMN
from ymtools.src.gop.column_types import COLUMN_TYPES, ColumnType, decode_cell, decode_unknown_cell
from ymtools.src.gop.exceptions import GopException

__all__ = ["GOP", "MetaNode", "GopException"]
log = logging.getLogger(__name__)

_REQUIRED_TABLES = (b"GOP GFIN", b"GOP GMET", b"GOP GREC", b"GENESTRT", b"GOP GDAT")


@dataclass(slots=True)
class MetaNode:
    """Metadata node. Either `values` (leaf node, may be empty) or `children` is used, never both."""
    name: str
    values: list[str] | None = None
    children: list["MetaNode"] = field(default_factory=list)


class GOP:
    def __init__(self, gfin: GOP_GFIN, gmet: GOP_GMET, grec: GOP_GREC, genestrt: GENESTRT, gdat: GOP_GDAT) -> None:
        self._GFIN = gfin
        self._GMET = gmet
        self._GREC = grec
        self._GENESTRT = genestrt
        self._GDAT = gdat

        self._COLUMN_NAMES: list[str] = [self._get_string(col.NAME_IDX, "column name") for col in grec.COLUMN_LIST]
        self._COLUMN_TYPES: list[ColumnType | None] = [COLUMN_TYPES.get(col.TYPE) for col in grec.COLUMN_LIST]  # None: unknown type
        self._COLUMN_SIZES: list[int] = self._calc_column_sizes()

    @classmethod
    def read_gop(cls, path: Path) -> "GOP":
        log.info(f"reading GOP: {path}")

        bodies: dict[bytes, bytes] = {}
        try:
            file_size = path.stat().st_size
            with BinaryReader(path) as br:
                if br.read_bytes(8) not in (b"GOP GFIN", b"ENDIBIGE", b"ENDILTLE"):
                    raise GopException("This is not a gop file")
                br.seek(0)

                # ====================== read all tables ======================
                while True:
                    signature, body = read_table(br, file_size)
                    log.info(f"Processing table {signature.decode('ascii', 'replace')}")
                    if signature == b"GENEEOF ":
                        break
                    if signature == b"ENDIBIGE":
                        raise GopException("Big endian gop file is not supported")
                    if signature == b"ENDILTLE":  # little endian is the default, so nothing to do
                        continue
                    if signature not in _REQUIRED_TABLES:
                        log.warning(f"Unknown table is ignored: {signature!r}")
                        continue
                    if signature in bodies:
                        raise GopException(f"Table '{signature.decode('ascii')}' appears more than once")
                    bodies[signature] = body
        except EOFError as e:
            raise GopException(f"The gop file is truncated or GENEEOF is missing: {e}") from e
        except OSError as e:
            raise GopException(f"Cannot read the gop file: {e}") from e

        missing = [sig.decode("ascii") for sig in _REQUIRED_TABLES if sig not in bodies]
        if missing:
            raise GopException(f"Required table(s) not found: {', '.join(missing)}")

        # ====================== parse tables ======================
        try:
            gop = cls(
                gfin=parse_gfin(bodies[b"GOP GFIN"]),
                gmet=parse_gmet(bodies[b"GOP GMET"]),
                grec=parse_grec(bodies[b"GOP GREC"]),
                genestrt=parse_genestrt(bodies[b"GENESTRT"]),
                gdat=parse_gdat(bodies[b"GOP GDAT"]),
            )
        except struct.error as e:
            raise GopException(f"The gop file is malformed: {e}") from e
        return gop

    # ====================== getters ======================
    def get_version(self) -> int:
        return self._GFIN.VERSION

    def get_gfin(self) -> GOP_GFIN:
        return self._GFIN

    def get_string_list(self) -> list[str]:
        return self._GENESTRT.STRING_LIST

    def get_columns(self) -> list[GREC_COLUMN]:
        return self._GREC.COLUMN_LIST

    def get_column_names(self) -> list[str]:
        return self._COLUMN_NAMES

    def get_column_types(self) -> list[ColumnType | None]:
        return self._COLUMN_TYPES

    def get_column_sizes(self) -> list[int]:
        return self._COLUMN_SIZES

    def get_record_size(self) -> int:
        return self._GDAT.RECORD_SIZE

    def get_record_count(self) -> int:
        return self._GDAT.RECORD_COUNT

    # ====================== metadata ======================
    def get_meta_tree(self) -> MetaNode:
        def convert(node: GMET_NODE) -> MetaNode:
            name = self._get_string(node.NAME_IDX, "metadata node name")
            kinds = {item.KIND for item in node.ITEM_LIST}
            if kinds == {0, 1}:
                raise GopException(f"The metadata node '{name}' has both values and child nodes")
            if 1 in kinds:
                return MetaNode(name=name, children=[convert(item.CHILD) for item in node.ITEM_LIST])
            return MetaNode(name=name, values=[self._get_string(item.VALUE, f"metadata value of '{name}'") for item in node.ITEM_LIST])

        return convert(self._GMET.ROOT)

    # ====================== records ======================
    def read_rows(self) -> list[list[object]]:
        """Decode every record. Unknown types are returned as a hex string. A null string is None."""
        string_list = self._GENESTRT.STRING_LIST
        columns = self._GREC.COLUMN_LIST

        rows: list[list[object]] = []
        for row_idx, record in enumerate(self._GDAT.RECORD_LIST):
            row: list[object] = []
            for i, col in enumerate(columns):
                raw = record[col.OFFSET:col.OFFSET + self._COLUMN_SIZES[i]]
                col_type = self._COLUMN_TYPES[i]
                try:
                    row.append(decode_unknown_cell(raw) if col_type is None else decode_cell(col_type, raw, string_list))
                except GopException as e:
                    raise GopException(f"Row #{row_idx}, column '{self._COLUMN_NAMES[i]}': {e}") from e
            rows.append(row)
        return rows

    # ====================== internal ======================
    def _get_string(self, idx: int, what: str) -> str:
        string_list = self._GENESTRT.STRING_LIST
        if idx >= len(string_list):
            raise GopException(f"The string index {idx} of {what} is out of range(string count: {len(string_list)})")
        return string_list[idx]

    def _calc_column_sizes(self) -> list[int]:
        """Size of each column. The size of an unknown type is the distance to the next column (or to the end of the record)."""
        record_size = self._GDAT.RECORD_SIZE
        columns = self._GREC.COLUMN_LIST
        offsets = sorted({col.OFFSET for col in columns})

        sizes: list[int] = []
        for col, col_type in zip(columns, self._COLUMN_TYPES):
            if col_type is not None:
                size = col_type.SIZE
            else:
                size = next((o for o in offsets if o > col.OFFSET), record_size) - col.OFFSET
            if size <= 0 or col.OFFSET + size > record_size:
                raise GopException(f"The column '{self._get_string(col.NAME_IDX, 'column name')}' (offset: {col.OFFSET}, size: {size}) does not fit in the record (size: {record_size})")
            sizes.append(size)
        return sizes
