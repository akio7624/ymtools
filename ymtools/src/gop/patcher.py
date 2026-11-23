import json
import logging
import math
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from ymtools.src.apkidx.structure._validator import raise_if_invalid
from ymtools.src.gop._txt import EMPTY_MARK, NULL_MARK, parse_text, unescape
from ymtools.src.gop._xlsx import MAX_CELL_LENGTH, autofit
from ymtools.src.gop.column_types import COLUMN_TYPES, KIND_BOOL, KIND_FLOAT, KIND_INT, KIND_STRING, KIND_VEC_INT
from ymtools.src.gop.exceptions import GopPatchException

log = logging.getLogger(__name__)


"""
txt 패치 과정 정리
1. txt를 읽어 컬럼 이름과 레코드의 값 목록으로 나눈다
2. xlsx를 열어 GDAT, GREC 시트를 확인한다(컬럼 이름과 순서, 레코드 개수가 txt와 같아야 한다)
3. txt의 각 값을 GREC의 타입에 맞는 셀 값으로 변환한다(형식과 범위를 확인하며 위반은 모아서 보고한다)
4. 변경된 셀의 값만 GDAT에 쓴다(서식과 잠금은 그대로 둔다)
5. 임시 파일에 저장한 뒤 출력 파일로 이름을 바꾼다(중간에 실패하면 지워져야함)
6. 끝

레코드의 추가, 삭제와 컬럼의 변경은 지원하지 않는다. 값의 수정만 가능하다
"""

MAX_REPORTED_VIOLATIONS = 100
FLOAT32_MAX = 3.4028234663852886e38
FLOAT_PATTERN = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")
INT_PATTERN = re.compile(r"-?\d+")
HEX_PATTERN = re.compile(r"[0-9A-Fa-f]{2}( [0-9A-Fa-f]{2})*")
INT_RANGES = {"b": (-(2 ** 7), 2 ** 7 - 1), "h": (-(2 ** 15), 2 ** 15 - 1), "i": (-(2 ** 31), 2 ** 31 - 1), "B": (0, 2 ** 8 - 1), "H": (0, 2 ** 16 - 1), "I": (0, 2 ** 32 - 1)}


class GopPatcher:
    def __init__(self, txt_path: Path, xlsx_path: Path, output_path: Path | None = None) -> None:
        self.TXT_PATH = txt_path
        self.XLSX_PATH = xlsx_path
        self.OUTPUT_PATH = output_path if output_path is not None else xlsx_path
        self.TEMP_PATH = self.OUTPUT_PATH.with_name(self.OUTPUT_PATH.name + ".tmp")

    def run(self) -> int:
        log.info("GopPatcher starting")

        for path in (self.TXT_PATH, self.XLSX_PATH):
            if not path.is_file():
                raise_if_invalid([f"File not found: {path}"], GopPatchException)
        if not self.XLSX_PATH.name.endswith(".xlsx"):
            raise_if_invalid([f"This is not xlsx file: {self.XLSX_PATH}"], GopPatchException)
        if self.OUTPUT_PATH.resolve() == self.TXT_PATH.resolve():
            raise_if_invalid([f"The output path must not be the same as the txt path: {self.OUTPUT_PATH}"], GopPatchException)

        # read txt
        log.info(f"Read txt: {self.TXT_PATH}")
        names, rows, first_lines = parse_text(self.TXT_PATH.read_text(encoding="utf-8-sig"))

        # read xlsx
        log.info(f"Read xlsx: {self.XLSX_PATH}")
        wb = load_workbook(self.XLSX_PATH)
        for sheet_name in ("GDAT", "GREC"):
            if sheet_name not in wb.sheetnames:
                raise_if_invalid([f"The sheet '{sheet_name}' is not found in {self.XLSX_PATH}"], GopPatchException)
        gdat = wb["GDAT"]
        grec = wb["GREC"]

        columns: list[tuple[str, int, int]] = []  # name, type id, size
        for r in range(2, grec.max_row + 1):
            if grec.cell(r, 1).value is None:
                break
            columns.append((grec.cell(r, 1).value, grec.cell(r, 3).value, grec.cell(r, 5).value))
        header = [gdat.cell(1, c).value for c in range(1, len(columns) + 1)]
        row_count = max((r for r in range(2, gdat.max_row + 1) if any(gdat.cell(r, c).value is not None for c in range(1, len(columns) + 1))), default=1) - 1

        violations: list[str] = []
        if [name for name, _, _ in columns] != header:
            violations.append("The column names of GREC and the header of GDAT are different")
        if names != header:
            first = next((i for i, (a, b) in enumerate(zip(names, header)) if a != b), min(len(names), len(header)))
            violations.append(f"The column names of the txt must be the same as the header of GDAT (first difference at column #{first}), txt: {names[first:first + 1]}, xlsx: {header[first:first + 1]}, column count: txt {len(names)}, xlsx {len(header)}")
        if len(rows) != row_count:
            violations.append(f"The record count of the txt must be the same as GDAT, txt: {len(rows)}, xlsx: {row_count}")
        raise_if_invalid(violations, GopPatchException)

        # convert the values of txt
        log.info("Convert values")
        new_rows: list[list[object]] = []
        for r, values in enumerate(rows):
            new_row: list[object] = []
            for c, (value, (name, type_id, size)) in enumerate(zip(values, columns)):
                try:
                    new_row.append(self._convert(type_id, size, value))
                except ValueError as e:
                    violations.append(f"line {first_lines[r] + c}: record #{r} column '{name}': {e}")
            new_rows.append(new_row)
        if len(violations) > MAX_REPORTED_VIOLATIONS:
            violations = violations[:MAX_REPORTED_VIOLATIONS] + [f"... and {len(violations) - MAX_REPORTED_VIOLATIONS} more"]
        raise_if_invalid(violations, GopPatchException)

        # patch GDAT
        changed = 0
        for r, new_row in enumerate(new_rows, 2):
            for c, value in enumerate(new_row, 1):
                cell = gdat.cell(r, c)
                if cell.value == value and isinstance(cell.value, bool) == isinstance(value, bool):  # 170.0 is read back as 170
                    continue
                cell.value = value
                if isinstance(value, str):
                    cell.data_type = "s"  # a string that starts with '=' must not be a formula
                changed += 1
        log.info(f"Changed cells: {changed}")

        if changed == 0 and self.OUTPUT_PATH.resolve() == self.XLSX_PATH.resolve():
            log.info("Nothing to patch")
            return 0

        autofit(gdat, grow_only=True)
        wb.properties.creator = None
        wb.properties.lastModifiedBy = None

        self.OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            log.info("Write xlsx")
            wb.save(self.TEMP_PATH)
            self.TEMP_PATH.replace(self.OUTPUT_PATH)
        except OSError as e:
            self.TEMP_PATH.unlink(missing_ok=True)
            raise_if_invalid([f"Cannot write {self.OUTPUT_PATH}, is it opened in another program? ({e})"], GopPatchException)
        except BaseException:
            self.TEMP_PATH.unlink(missing_ok=True)
            raise

        log.info("GopPatcher finished: %s", self.OUTPUT_PATH)
        return 0

    @staticmethod
    def _convert(type_id: int, size: int, text: str) -> object:
        # inverse of the conversion of the dumper: text -> value of the cell
        col_type = COLUMN_TYPES.get(type_id)
        if col_type is None:  # unknown type
            if not HEX_PATTERN.fullmatch(text):
                raise ValueError(f"must be hexadecimal bytes separated by a space (ex: 00 1F), current: '{text}'")
            if len(text.split(" ")) != size:
                raise ValueError(f"must have {size} byte(s), current: {len(text.split(' '))}")
            return text.upper()

        if col_type.KIND == KIND_STRING:
            if text == EMPTY_MARK:
                return None
            if text == NULL_MARK:
                return NULL_MARK
            value = unescape(text)
            if len(value) > MAX_CELL_LENGTH or ILLEGAL_CHARACTERS_RE.search(value):
                raise ValueError("the string cannot be stored in a cell of xlsx")
            return value

        if col_type.KIND == KIND_BOOL:
            if text not in ("true", "false"):
                raise ValueError(f"must be true or false, current: '{text}'")
            return text == "true"

        if col_type.KIND == KIND_INT:
            return GopPatcher._parse_int(text, col_type.FMT, col_type.NAME)

        if col_type.KIND == KIND_FLOAT:
            return GopPatcher._parse_float(text, col_type.NAME)

        # vectors and colors: a JSON array
        count = int(col_type.FMT[:-1] or 1)
        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"must be a JSON array like [1, 2], current: '{text}'") from None
        if not isinstance(items, list) or len(items) != count:
            raise ValueError(f"must be a JSON array of {count} number(s), current: '{text}'")
        if col_type.KIND == KIND_VEC_INT:
            return json.dumps([GopPatcher._parse_int(json.dumps(item), col_type.FMT[-1], col_type.NAME) for item in items])
        floats = [GopPatcher._parse_float(json.dumps(item), col_type.NAME) for item in items]
        if any(isinstance(f, str) for f in floats):
            raise ValueError(f"nan and inf are not supported in {col_type.NAME}, current: '{text}'")
        return json.dumps(floats)

    @staticmethod
    def _parse_int(text: str, fmt: str, type_name: str) -> int:
        if not INT_PATTERN.fullmatch(text):
            raise ValueError(f"must be an integer, current: '{text}'")
        low, high = INT_RANGES[fmt]
        if not low <= int(text) <= high:
            raise ValueError(f"{type_name} must be between {low} and {high}, current: {text}")
        return int(text)

    @staticmethod
    def _parse_float(text: str, type_name: str) -> float | str:
        if text in ("nan", "inf", "-inf", "NaN", "Infinity", "-Infinity"):
            return str(float(text.replace("Infinity", "inf").replace("NaN", "nan")))
        if not FLOAT_PATTERN.fullmatch(text):
            raise ValueError(f"must be a number, current: '{text}'")
        value = float(text)
        if not math.isfinite(value) or abs(value) > FLOAT32_MAX:
            raise ValueError(f"{type_name} must be between -{FLOAT32_MAX} and {FLOAT32_MAX}, current: {text}")
        return value
