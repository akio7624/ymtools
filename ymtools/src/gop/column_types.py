import math
import struct
from dataclasses import dataclass
from typing import Final

__all__ = ["ColumnType", "COLUMN_TYPES", "UNKNOWN_TYPE_NAME", "decode_cell", "decode_unknown_cell"]

UNKNOWN_TYPE_NAME: Final[str] = "Unknown"

KIND_INT: Final[str] = "int"
KIND_FLOAT: Final[str] = "float"
KIND_BOOL: Final[str] = "bool"
KIND_STRING: Final[str] = "string"  # RecId and String, index of GENESTRT. a negative value means null
KIND_VEC_INT: Final[str] = "vec_int"
KIND_VEC_FLOAT: Final[str] = "vec_float"


@dataclass(frozen=True, slots=True)
class ColumnType:
    ID: int
    NAME: str
    SIZE: int
    FMT: str
    KIND: str


def _t(type_id: int, name: str, size: int, fmt: str, kind: str) -> tuple[int, ColumnType]:
    return type_id, ColumnType(type_id, name, size, fmt, kind)


# only the types that are confirmed in the document. the others (0, 1, 6, 10, 12, 16-21, 26, 28, 30) are treated as unknown
COLUMN_TYPES: Final[dict[int, ColumnType]] = dict([
    _t(2, "Enum", 4, "i", KIND_INT),
    _t(3, "Int8", 1, "b", KIND_INT),
    _t(4, "Int16", 2, "h", KIND_INT),
    _t(5, "Int32", 4, "i", KIND_INT),
    _t(7, "UInt8", 1, "B", KIND_INT),
    _t(8, "UInt16", 2, "H", KIND_INT),
    _t(9, "UInt32", 4, "I", KIND_INT),
    _t(11, "Float32", 4, "f", KIND_FLOAT),
    _t(13, "bool", 1, "B", KIND_BOOL),
    _t(14, "RecId", 4, "i", KIND_STRING),
    _t(15, "String", 4, "i", KIND_STRING),
    _t(22, "FRgba", 16, "4f", KIND_VEC_FLOAT),
    _t(23, "FRgb", 12, "3f", KIND_VEC_FLOAT),
    _t(24, "Rgba", 4, "4B", KIND_VEC_INT),
    _t(25, "Rgb", 3, "3B", KIND_VEC_INT),
    _t(27, "Vector3", 12, "3f", KIND_VEC_FLOAT),
    _t(29, "IVector2", 8, "2i", KIND_VEC_INT),
    _t(31, "IVector4", 16, "4i", KIND_VEC_INT),
])

_STRUCTS: Final[dict[int, struct.Struct]] = {type_id: struct.Struct("<" + t.FMT) for type_id, t in COLUMN_TYPES.items()}


def to_float32_shortest(value: float) -> float:
    # the shortest decimal that is read back as the same float32 (0.2 instead of 0.20000000298...)
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

    if col_type.KIND == KIND_INT:
        return values[0]
    if col_type.KIND == KIND_FLOAT:
        return to_float32_shortest(values[0])
    if col_type.KIND == KIND_BOOL:
        return values[0] == 1
    if col_type.KIND == KIND_STRING:
        return None if values[0] < 0 else string_list[values[0]]
    if col_type.KIND == KIND_VEC_FLOAT:
        return tuple(to_float32_shortest(v) for v in values)
    return tuple(values)


def decode_unknown_cell(raw: bytes) -> str:
    return raw.hex(" ").upper()
