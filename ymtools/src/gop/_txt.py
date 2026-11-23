import json
import math

from ymtools.src.apkidx.structure._validator import raise_if_invalid
from ymtools.src.gop.column_types import COLUMN_TYPES, KIND_BOOL, KIND_FLOAT, KIND_STRING, KIND_VEC_FLOAT, KIND_VEC_INT, ColumnType
from ymtools.src.gop.exceptions import GopPatchException
from ymtools.src.gop.gop import GOP
from ymtools.src.gop.utils import read_rows

__all__ = ["build_text", "parse_text", "unescape", "SEPARATOR", "NULL_MARK", "EMPTY_MARK"]


"""
txt 형식 정리
- 컬럼 이름을 한 줄씩 적고, 빈 줄, 구분선, 빈 줄 다음에 레코드를 적는다
- 레코드는 값을 한 줄씩 적으며, 레코드 사이는 빈 줄로 구분한다
- 빈 문자열은 `""`, null은 `<null>`, 문자열이 그 자체와 같은 경우 앞에 `\\`를 붙인다
- 문자열의 `\\`는 `\\\\`, 줄바꿈은 `\\n`, `\\r`, `\\t`, 그 외 제어문자와 줄바꿈으로 취급되는 문자는 `\\xNN`, `\\uNNNN`으로 쓴다
- bool은 true/false, 실수는 가장 짧은 표기, 벡터와 색상은 JSON 배열, 알 수 없는 타입은 hex 문자열
"""

SEPARATOR = "// ------------------"
NULL_MARK = "<null>"
EMPTY_MARK = '""'

_ESCAPES = {"\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_UNESCAPES = {"\\": "\\", "n": "\n", "r": "\r", "t": "\t"}
_LINE_BREAKS = {0x85, 0x2028, 0x2029}


def build_text(gop: GOP) -> str:
    grec = gop.get_grec()
    string_list = gop.get_string_list()
    col_names = [string_list[col.NAME_IDX] for col in grec.COLUMN_LIST]
    col_types = [COLUMN_TYPES.get(col.TYPE) for col in grec.COLUMN_LIST]

    lines: list[str] = [_escape(name) for name in col_names]
    lines += ["", SEPARATOR]
    for row in read_rows(grec, gop.get_gdat(), string_list):
        lines.append("")
        lines += [_to_text(col_type, value) for col_type, value in zip(col_types, row)]
    return "\n".join(lines) + "\n"


def parse_text(text: str) -> tuple[list[str], list[list[str]], list[int]]:
    """Returns the column names, the raw value lines of each record and the line number of the first value of each record."""
    # the file may be checked out with CRLF, and a CR in a value is always escaped
    lines = text.replace("\r\n", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()

    if SEPARATOR not in lines:
        raise_if_invalid([f"The separator line '{SEPARATOR}' is not found"], GopPatchException)
    separator_idx = lines.index(SEPARATOR)
    if separator_idx == 0 or lines[separator_idx - 1] != "":
        raise_if_invalid(["The separator line must be preceded by a blank line"], GopPatchException)

    violations: list[str] = []
    names: list[str] = []
    for i, line in enumerate(lines[:separator_idx - 1]):
        try:
            names.append(unescape(line))
        except ValueError as e:
            violations.append(f"line {i + 1}: {e}")

    column_count = separator_idx - 1
    rows: list[list[str]] = []
    first_lines: list[int] = []
    i = separator_idx + 1
    while i < len(lines):
        if lines[i] != "":
            violations.append(f"line {i + 1}: a blank line is expected before a record")
            break
        values = lines[i + 1:i + 1 + column_count]
        if len(values) != column_count:
            violations.append(f"line {i + 1}: the record #{len(rows)} is incomplete, {column_count} values are required but {len(values)} found")
            break
        for k, value in enumerate(values):
            if value == "":
                violations.append(f"line {i + 2 + k}: a value must not be an empty line, an empty string is written as {EMPTY_MARK}")
        rows.append(values)
        first_lines.append(i + 2)
        i += 1 + column_count

    if violations:
        raise_if_invalid(violations, GopPatchException)
    return names, rows, first_lines


def unescape(text: str) -> str:
    if text in ("\\" + EMPTY_MARK, "\\" + NULL_MARK):
        return text[1:]

    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        code = text[i + 1:i + 2]
        if code in _UNESCAPES:
            out.append(_UNESCAPES[code])
            i += 2
        elif code in ("x", "u"):
            width = 2 if code == "x" else 4
            digits = text[i + 2:i + 2 + width]
            if len(digits) != width or any(c not in "0123456789abcdefABCDEF" for c in digits):
                raise ValueError(f"invalid escape sequence '\\{code}{digits}'")
            out.append(chr(int(digits, 16)))
            i += 2 + width
        else:
            raise ValueError(f"invalid escape sequence '\\{code}'")
    return "".join(out)


def _escape(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ch == "\x7f" or ord(ch) in _LINE_BREAKS:
            out.append(f"\\x{ord(ch):02x}" if ord(ch) < 0x100 else f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    escaped = "".join(out)
    return "\\" + escaped if escaped in (EMPTY_MARK, NULL_MARK) else escaped


def _to_text(col_type: ColumnType | None, value: object) -> str:
    if col_type is None:
        return str(value)
    if col_type.KIND == KIND_STRING:
        if value is None:
            return NULL_MARK
        return EMPTY_MARK if value == "" else _escape(value)
    if col_type.KIND == KIND_BOOL:
        return "true" if value else "false"
    if col_type.KIND == KIND_FLOAT and not math.isfinite(value):
        return str(value)
    if col_type.KIND in (KIND_VEC_INT, KIND_VEC_FLOAT):
        return json.dumps(list(value))
    return str(value)
