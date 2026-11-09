from pathlib import Path
from typing import Iterable


class BinaryWriter:
    def __init__(self, path: Path) -> None:
        self.file = open(path, "wb")

    def __enter__(self) -> "BinaryWriter":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def tell(self) -> int:
        return self.file.tell()

    def seek(self, pos: int) -> None:
        self.file.seek(pos)

    def flush(self) -> None:
        self.file.flush()

    def close(self) -> None:
        self.file.close()

    def write_bytes(self, data: bytes) -> None:
        written = self.file.write(data)
        if written != len(data):
            raise EOFError(f"expected {len(data)} bytes at offset {self.file.tell() - written}, wrote {written}")

    def write_chunks(self, chunks: Iterable[bytes]) -> int:
        total = 0
        for chunk in chunks:
            self.write_bytes(chunk)
            total += len(chunk)
        return total

    def write_zeros(self, size: int) -> None:
        self.write_bytes(bytes(size))

    def write_align(self, align: int) -> int:
        size = (-self.tell()) % align
        self.write_zeros(size)
        return size
