import struct
from pathlib import Path
from typing import Iterator

from ymtools.src.typealias.ctype import uchar, uint16, uint32, uint64

_UCHAR = struct.Struct("<B")
_UINT16 = struct.Struct("<H")
_UINT32 = struct.Struct("<I")
_UINT64 = struct.Struct("<Q")


class BinaryReader:
    def __init__(self, path: Path) -> None:
        self.file = open(path, "rb")

    def __enter__(self) -> "BinaryReader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def tell(self) -> int:
        return self.file.tell()

    def seek(self, pos: int) -> None:
        self.file.seek(pos)

    def skip(self, size: int) -> None:
        self.file.seek(size, 1)

    def close(self) -> None:
        self.file.close()

    def read_bytes(self, size: int) -> bytes:
        data = self.file.read(size)
        if len(data) != size:
            raise EOFError(f"expected {size} bytes at offset {self.file.tell() - len(data)}, got {len(data)}")
        return data

    def read_string(self, size: int) -> str:
        return self.read_bytes(size).decode("utf-8")

    def read_uchar(self) -> uchar:
        return _UCHAR.unpack(self.read_bytes(_UCHAR.size))[0]

    def read_uint16(self) -> uint16:
        return _UINT16.unpack(self.read_bytes(_UINT16.size))[0]

    def read_uint32(self) -> uint32:
        return _UINT32.unpack(self.read_bytes(_UINT32.size))[0]

    def read_uint64(self) -> uint64:
        return _UINT64.unpack(self.read_bytes(_UINT64.size))[0]

    def read_struct(self, fmt: struct.Struct) -> tuple:
        return fmt.unpack(self.read_bytes(fmt.size))

    def iter_struct(self, fmt: struct.Struct, count: int) -> Iterator[tuple]:
        return fmt.iter_unpack(self.read_bytes(fmt.size * count))
