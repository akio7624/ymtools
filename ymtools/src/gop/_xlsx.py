import json
import logging
import math
import unicodedata

from openpyxl import Workbook
from openpyxl.cell.cell import Cell, ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook.protection import WorkbookProtection
from openpyxl.worksheet.worksheet import Worksheet

from ymtools.src.gop.column_types import COLUMN_TYPES, KIND_FLOAT, KIND_STRING, KIND_VEC_FLOAT, KIND_VEC_INT, UNKNOWN_TYPE_NAME, ColumnType
from ymtools.src.gop.exceptions import GopDumpException
from ymtools.src.gop.gop import GOP
from ymtools.src.gop.utils import MetaNode, build_meta_tree, get_column_sizes, read_rows

__all__ = ["build_workbook"]
log = logging.getLogger(__name__)

NULL_MARK = "<null>"
MAX_TREE_DEPTH = 3  # the names of the tree are written in the columns A-D
MAX_CELL_LENGTH = 32767

CENTER = Alignment(horizontal="center")
BOLD = Font(bold=True)
UNLOCKED = Protection(locked=False)
LOCKED = Protection(locked=True)


def build_workbook(gop: GOP) -> Workbook:
    wb = Workbook()
    col_names = [gop.get_string_list()[col.NAME_IDX] for col in gop.get_grec().COLUMN_LIST]
    col_types = [COLUMN_TYPES.get(col.TYPE) for col in gop.get_grec().COLUMN_LIST]

    log.info("Make sheet GDAT")
    _make_gdat(wb.active, gop, col_names, col_types)
    log.info("Make sheet GREC")
    _make_grec(wb.create_sheet("GREC"), gop, col_names, col_types)
    log.info("Make sheet GMAT")
    _make_gmat(wb.create_sheet("GMAT"), gop)
    log.info("Make sheet GFIN")
    _make_gfin(wb.create_sheet("GFIN"), gop)

    for ws in wb.worksheets:
        _autofit(ws)
    _protect(wb, col_types)

    wb.properties.creator = None
    wb.properties.lastModifiedBy = None
    return wb


def _put(ws: Worksheet, row: int, col: int, value: object, text: bool = False) -> Cell:
    cell = ws.cell(row, col)
    if isinstance(value, str):
        if len(value) > MAX_CELL_LENGTH:
            raise GopDumpException(f"The value of {ws.title}!{cell.coordinate} is too long for a cell: {len(value)} characters")
        if ILLEGAL_CHARACTERS_RE.search(value):
            raise GopDumpException(f"The value of {ws.title}!{cell.coordinate} has characters that cannot be stored in xlsx: {value!r}")
        cell.value = value
        cell.data_type = "s"  # a string that starts with '=' must not be a formula
    else:
        cell.value = value
    if text:
        cell.number_format = "@"
    return cell


def _put_header(ws: Worksheet, col: int, name: str) -> None:
    cell = _put(ws, 1, col, name)
    cell.font = BOLD
    cell.alignment = CENTER


def _is_text_column(col_type: ColumnType | None) -> bool:
    return col_type is None or col_type.KIND in (KIND_STRING, KIND_VEC_INT, KIND_VEC_FLOAT)


def _to_cell_value(col_type: ColumnType | None, value: object) -> object:
    if col_type is None:
        return value
    if col_type.KIND == KIND_STRING:
        if value is None:
            return NULL_MARK
        return value if value != "" else None  # an empty string is an empty cell
    if col_type.KIND in (KIND_VEC_INT, KIND_VEC_FLOAT):
        return json.dumps(list(value))
    if col_type.KIND == KIND_FLOAT and not math.isfinite(value):
        return str(value)  # nan and inf cannot be stored in a number cell
    return value


# ====================== sheets ======================
def _make_gdat(ws: Worksheet, gop: GOP, col_names: list[str], col_types: list[ColumnType | None]) -> None:
    ws.title = "GDAT"
    for i, name in enumerate(col_names, 1):
        _put_header(ws, i, name)

    rows = read_rows(gop.get_grec(), gop.get_gdat(), gop.get_string_list())
    for r, row in enumerate(rows, 2):
        for i, (col_type, value) in enumerate(zip(col_types, row), 1):
            _put(ws, r, i, _to_cell_value(col_type, value), text=_is_text_column(col_type))
    ws.freeze_panes = "B2"


def _make_grec(ws: Worksheet, gop: GOP, col_names: list[str], col_types: list[ColumnType | None]) -> None:
    for i, header in enumerate(["Name", "Type", "TypeId", "Offset", "Size", "Lang"], 1):
        _put_header(ws, i, header)

    columns = gop.get_grec().COLUMN_LIST
    sizes = get_column_sizes(columns, gop.get_gdat().RECORD_SIZE)
    for r, (col, name, col_type, size) in enumerate(zip(columns, col_names, col_types, sizes), 2):
        type_name = UNKNOWN_TYPE_NAME if col_type is None else col_type.NAME
        for i, value in enumerate([name, type_name, col.TYPE, col.OFFSET, size, col.LANG_FLAG], 1):
            _put(ws, r, i, value)


def _make_gmat(ws: Worksheet, gop: GOP) -> None:
    row = 1

    def write(node: MetaNode, depth: int, new_row: bool) -> None:
        nonlocal row
        if depth > MAX_TREE_DEPTH:
            raise GopDumpException(f"The metadata tree is deeper than {MAX_TREE_DEPTH} levels at the node '{node.name}'")
        if new_row:
            row += 1
        _put(ws, row, depth + 1, node.name)

        children = [item for item in node.items if isinstance(item, MetaNode)]
        if children and len(children) != len(node.items):
            raise GopDumpException(f"The metadata node '{node.name}' has both values and child nodes")
        if children:
            for i, child in enumerate(children):
                write(child, depth + 1, i > 0)  # the first child shares the row of its parent
        else:
            _put(ws, row, 5, "=").alignment = CENTER
            _put(ws, row, 6, json.dumps(node.items, ensure_ascii=False), text=True)

    write(build_meta_tree(gop.get_gmet(), gop.get_string_list()), 0, False)


def _make_gfin(ws: Worksheet, gop: GOP) -> None:
    _put(ws, 1, 1, "version")
    _put(ws, 1, 2, gop.get_gfin().VERSION)


# ====================== layout ======================
def _autofit(ws: Worksheet, padding: int = 3, max_width: int = 255) -> None:
    widths: dict[str, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                width = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(cell.value)) + (1 if cell.font.bold else 0)
                widths[cell.column_letter] = max(widths.get(cell.column_letter, 0), width)
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = min(width + padding, max_width)


def _protect(wb: Workbook, col_types: list[ColumnType | None]) -> None:
    # GDAT: only the header row is locked, GREC: the whole sheet is locked, GMAT and GFIN: not protected
    gdat = wb["GDAT"]
    for row in gdat.iter_rows(min_row=2):
        for cell in row:
            cell.protection = UNLOCKED
    for cell in gdat[1]:
        cell.protection = LOCKED

    # the column style is applied to the cells of new records
    for i, col_type in enumerate(col_types, 1):
        col_dim = gdat.column_dimensions[get_column_letter(i)]
        col_dim.protection = UNLOCKED
        if _is_text_column(col_type):
            col_dim.number_format = "@"

    gdat.protection.sheet = True
    gdat.protection.insertRows = False
    gdat.protection.deleteRows = False
    gdat.protection.formatColumns = False
    gdat.protection.formatRows = False

    grec = wb["GREC"]
    grec.protection.sheet = True
    grec.protection.formatColumns = False
    grec.protection.formatRows = False

    wb.security = WorkbookProtection(lockStructure=True)
