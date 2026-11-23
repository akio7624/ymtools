import math
import struct
from dataclasses import dataclass
from typing import Final

from ymtools.src.gop.exceptions import GopException

__all__ = ["ColumnType", "COLUMN_TYPES", "UNKNOWN_TYPE_NAME", "decode_cell", "decode_unknown_cell", "to_float32_shortest"]

UNKNOWN_TYPE_NAME: Final[str] = "Unknown"

KIND_INT: Final[str] = "int"
KIND_FLOAT32: Final[str] = "float32"
KIND_BOOL: Final[str] = "bool"
KIND_STRING: Final[str] = "string"  # RecId and String: index of GENESTRT, negative means null
KIND_VEC_INT: Final[str] = "vec_int"
KIND_VEC_FLOAT32: Final[str] = "vec_float32"


@dataclass(frozen=True, slots=True)
class ColumnType:
    ID: int
    NAME: str
    SIZE: int
    FMT: str  # struct format (little endian is implied)
    KIND: str


def _t(type_id: int, name: str, size: int, fmt: str, kind: str) -> tuple[int, ColumnType]:
    return type_id, ColumnType(type_id, name, size, fmt, kind)


# Only the types confirmed in the format document are listed. Any other type (0, 1, 6, 10, 12, 16-21, 26, 28, 30) is treated as unknown.
# The size of an unknown type can't be known from the type.
COLUMN_TYPES: Final[dict[int, ColumnType]] = dict([
    _t(2, "Enum", 4, "i", KIND_INT),
    _t(3, "Int8", 1, "b", KIND_INT),
    _t(4, "Int16", 2, "h", KIND_INT),
    _t(5, "Int32", 4, "i", KIND_INT),
    _t(7, "UInt8", 1, "B", KIND_INT),
    _t(8, "UInt16", 2, "H", KIND_INT),
    _t(9, "UInt32", 4, "I", KIND_INT),
    _t(11, "Float32", 4, "f", KIND_FLOAT32),
    _t(13, "bool", 1, "B", KIND_BOOL),
    _t(14, "RecId", 4, "i", KIND_STRING),
    _t(15, "String", 4, "i", KIND_STRING),
    _t(22, "FRgba", 16, "4f", KIND_VEC_FLOAT32),
    _t(23, "FRgb", 12, "3f", KIND_VEC_FLOAT32),
    _t(24, "Rgba", 4, "4B", KIND_VEC_INT),
    _t(25, "Rgb", 3, "3B", KIND_VEC_INT),
    _t(27, "Vector3", 12, "3f", KIND_VEC_FLOAT32),
    _t(29, "IVector2", 8, "2i", KIND_VEC_INT),
    _t(31, "IVector4", 16, "4i", KIND_VEC_INT),
])

_STRUCTS: Final[dict[int, struct.Struct]] = {type_id: struct.Struct("<" + t.FMT) for type_id, t in COLUMN_TYPES.items()}


def to_float32_shortest(value: float) -> float:
    """Return the shortest decimal that is read back as the same float32 (0.2 instead of 0.20000000298...)."""
    if not math.isfinite(value):
        return value
    for precision in range(1, 10):
        candidate = float(f"{value:.{precision}g}")
        try:
            if struct.unpack("<f", struct.pack("<f", candidate))[0] == value:
                return candidate
        except OverflowError:
            continue
    return value


def decode_cell(col_type: ColumnType, raw: bytes, string_list: list[str]) -> object:
    values = _STRUCTS[col_type.ID].unpack(raw)
    kind = col_type.KIND

    if kind == KIND_INT:
        return values[0]
    if kind == KIND_FLOAT32:
        return to_float32_shortest(values[0])
    if kind == KIND_BOOL:
        if values[0] not in (0, 1):
            raise GopException(f"bool value must be 0 or 1, current: {values[0]}")
        return values[0] == 1
    if kind == KIND_STRING:
        idx = values[0]
        if idx < 0:
            return None  # null
        if idx >= len(string_list):
            raise GopException(f"string index {idx} is out of range(string count: {len(string_list)})")
        return string_list[idx]
    if kind == KIND_VEC_FLOAT32:
        return tuple(to_float32_shortest(v) for v in values)
    return tuple(values)  # KIND_VEC_INT


def decode_unknown_cell(raw: bytes) -> str:
    return raw.hex(" ").upper()
