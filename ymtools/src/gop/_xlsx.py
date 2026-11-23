import json
import logging
import unicodedata
from typing import Final

from openpyxl import Workbook
from openpyxl.cell.cell import Cell, ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, Protection
from openpyxl.utils import get_column_letter
from openpyxl.workbook.protection import WorkbookProtection
from openpyxl.worksheet.worksheet import Worksheet

from ymtools.src.gop.column_types import COLUMN_TYPES, UNKNOWN_TYPE_NAME, ColumnType
from ymtools.src.gop.exceptions import GopException
from ymtools.src.gop.gop import GOP, MetaNode

__all__ = ["build_workbook"]
log = logging.getLogger(__name__)


"""
xlsx 레이아웃 정리
- GDAT: 1행은 컬럼 이름, 2행부터 레코드. 셀 값 표현은 아래와 같다
    - 정수는 숫자 셀, 단 64비트 정수는 엑셀 숫자 정밀도(15자리)를 넘으므로 텍스트 셀
    - 실수는 숫자 셀, bool은 TRUE/FALSE 셀
    - RecId, String은 텍스트 셀, 빈 문자열은 빈 셀, null은 `<null>`
    - 벡터/색상은 JSON 배열 문자열(예: [1.0, 2.5, 0.0]), 알 수 없는 타입은 hex 문자열
- GREC: Name, Type, TypeId, Offset, Size, Lang. 시트 전체가 잠긴다
- GMAT: 메타데이터 트리. A~D열에 노드 이름(깊이별), E열에 `=`, F열에 값 목록(JSON 배열 문자열)
    - 첫 번째 자식 노드는 부모와 같은 행에 적는다
- GFIN: version만 기록한다
"""

NULL_MARK: Final[str] = "<null>"
MAX_TREE_DEPTH: Final[int] = 3  # root is depth 0, and the name columns are A-D
MAX_CELL_LENGTH: Final[int] = 32767

_CENTER = Alignment(horizontal="center")
_BOLD = Font(bold=True)
_UNLOCKED = Protection(locked=False)
_LOCKED = Protection(locked=True)


def build_workbook(gop: GOP) -> Workbook:
    wb = Workbook()

    _build_gdat(wb.active, gop)
    _build_grec(wb.create_sheet("GREC"), gop)
    _build_gmat(wb.create_sheet("GMAT"), gop)
    _build_gfin(wb.create_sheet("GFIN"), gop)

    for ws in wb.worksheets:
        _autofit(ws)
    _protect(wb, gop)

    wb.properties.creator = None  # no author in the document information
    wb.properties.lastModifiedBy = None
    return wb


# ====================== helpers ======================
def _put(ws: Worksheet, row: int, col: int, value: object, text: bool = False) -> Cell:
    cell = ws.cell(row, col)
    if isinstance(value, str):
        if len(value) > MAX_CELL_LENGTH:
            raise GopException(f"The value of {ws.title}!{cell.coordinate} is too long for a cell: {len(value)} characters (max: {MAX_CELL_LENGTH})")
        if ILLEGAL_CHARACTERS_RE.search(value):
            raise GopException(f"The value of {ws.title}!{cell.coordinate} has characters that cannot be stored in xlsx: {value!r}")
        cell.value = value
        cell.data_type = "s"  # a string that starts with '=' must not be a formula
    else:
        cell.value = value
    if text:
        cell.number_format = "@"
    return cell


def _put_header(ws: Worksheet, col: int, name: str) -> None:
    cell = _put(ws, 1, col, name)
    cell.font = _BOLD
    cell.alignment = _CENTER


def _display_width(value: object) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(value))


def _autofit(ws: Worksheet, padding: int = 3, max_width: int = 255) -> None:
    """Widen every column to its longest cell. Full-width characters count as 2."""
    widths: dict[str, int] = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                width = _display_width(cell.value) + (1 if cell.font.bold else 0)
                widths[cell.column_letter] = max(widths.get(cell.column_letter, 0), width)
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = min(width + padding, max_width)


def _is_text_column(col_type: ColumnType | None) -> bool:
    if col_type is None:
        return True  # unknown type: hex string
    return col_type.KIND in ("string", "vec_int", "vec_float32") or col_type.ID in (6, 10)  # 64-bit integers


def _to_cell_value(col_type: ColumnType | None, value: object) -> object:
    """Convert a decoded value into what is stored in the cell. None means an empty cell."""
    if col_type is None:
        return value  # hex string
    kind = col_type.KIND
    if kind == "string":
        if value is None:
            return NULL_MARK
        return value if value != "" else None  # an empty string is an empty cell
    if kind in ("vec_int", "vec_float32"):
        return json.dumps(list(value))
    if col_type.ID in (6, 10):
        return str(value)
    if kind in ("float32", "float64") and not (value == value and abs(value) != float("inf")):
        return str(value)  # nan / inf cannot be stored in a number cell
    return value


# ====================== sheets ======================
def _build_gdat(ws: Worksheet, gop: GOP) -> None:
    ws.title = "GDAT"
    col_types = gop.get_column_types()

    for i, name in enumerate(gop.get_column_names(), 1):
        _put_header(ws, i, name)
    for r, row in enumerate(gop.read_rows(), 2):
        for i, (col_type, value) in enumerate(zip(col_types, row), 1):
            _put(ws, r, i, _to_cell_value(col_type, value), text=_is_text_column(col_type))
    ws.freeze_panes = "B2"


def _build_grec(ws: Worksheet, gop: GOP) -> None:
    for i, header in enumerate(["Name", "Type", "TypeId", "Offset", "Size", "Lang"], 1):
        _put_header(ws, i, header)
    for r, (col, name, col_type, size) in enumerate(zip(gop.get_columns(), gop.get_column_names(), gop.get_column_types(), gop.get_column_sizes()), 2):
        type_name = UNKNOWN_TYPE_NAME if col_type is None else col_type.NAME
        for i, value in enumerate([name, type_name, col.TYPE, col.OFFSET, size, col.LANG_FLAG], 1):
            _put(ws, r, i, value)


def _build_gmat(ws: Worksheet, gop: GOP) -> None:
    row = 1

    def emit(node: MetaNode, depth: int, new_row: bool) -> None:
        nonlocal row
        if depth > MAX_TREE_DEPTH:
            raise GopException(f"The metadata tree is deeper than {MAX_TREE_DEPTH} levels at '{node.name}'")
        if new_row:
            row += 1
        _put(ws, row, depth + 1, node.name)
        if node.values is not None:
            _put(ws, row, 5, "=").alignment = _CENTER
            _put(ws, row, 6, json.dumps(node.values, ensure_ascii=False), text=True)
        else:
            for i, child in enumerate(node.children):
                emit(child, depth + 1, i > 0)  # the first child shares the row of its parent

    emit(gop.get_meta_tree(), 0, False)


def _build_gfin(ws: Worksheet, gop: GOP) -> None:
    gfin = gop.get_gfin()
    if (gfin.unknown_1, gfin.unknown_2, gfin.unknown_3) != (1, 0, 0):
        log.warning(f"GFIN unknown fields are not (1, 0, 0) and are not dumped: ({gfin.unknown_1}, {gfin.unknown_2}, {gfin.unknown_3})")
    _put(ws, 1, 1, "version")
    _put(ws, 1, 2, gfin.VERSION)


# ====================== protection (no password) ======================
def _protect(wb: Workbook, gop: GOP) -> None:
    """GDAT: only the header row is locked / GREC: the whole sheet is locked / GMAT, GFIN: not protected."""
    gdat = wb["GDAT"]
    for row in gdat.iter_rows(min_row=2):
        for cell in row:
            cell.protection = _UNLOCKED
    for i, col_type in enumerate(gop.get_column_types(), 1):  # column style: cells created later (new records) are editable and keep the text format
        col_dim = gdat.column_dimensions[get_column_letter(i)]
        col_dim.protection = _UNLOCKED
        if _is_text_column(col_type):
            col_dim.number_format = "@"
    for cell in gdat[1]:
        cell.protection = _LOCKED

    gdat.protection.sheet = True
    gdat.protection.insertRows = False  # records can be added / removed
    gdat.protection.deleteRows = False
    gdat.protection.formatColumns = False  # column width and row height can be adjusted
    gdat.protection.formatRows = False

    grec = wb["GREC"]
    grec.protection.sheet = True
    grec.protection.formatColumns = False
    grec.protection.formatRows = False

    wb.security = WorkbookProtection(lockStructure=True)  # sheets cannot be added / deleted / renamed / moved
