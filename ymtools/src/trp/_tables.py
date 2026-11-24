from dataclasses import dataclass, field

from ymtools.src.typealias.ctype import uint32, uint64


@dataclass(slots=True)
class TRP_HEADER:
    SIGNATURE: uint32
    VERSION: uint32
    FILE_SIZE: uint64
    FILE_COUNT: uint32
    ENTRY_SIZE: uint32
    DEV_FLAG: uint32
    HASH: bytes
    PADDING: bytes

    _actual_file_size: int | None = field(default=None, init=False, repr=False, compare=False)
    _actual_hash: bytes | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def actual_file_size(self) -> int | None:
        return self._actual_file_size

    @actual_file_size.setter
    def actual_file_size(self, value: int | None) -> None:
        self._actual_file_size = value

    @property
    def actual_hash(self) -> bytes | None:
        return self._actual_hash

    @actual_hash.setter
    def actual_hash(self, value: bytes | None) -> None:
        self._actual_hash = value


@dataclass(slots=True)
class TRP_FILE_ENTRY:
    FILE_NAME: bytes
    unknown_1: bytes
    START_OFS: uint32
    unknown_2: uint32
    FILE_SIZE: uint32
    unknown_3: uint32
    PADDING: bytes

    @property
    def name(self) -> str:
        return self.FILE_NAME.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
