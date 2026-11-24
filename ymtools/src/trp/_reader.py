import struct

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.trp._tables import TRP_FILE_ENTRY, TRP_HEADER

__all__ = ["read_header", "read_entry_list"]


"""
trp 파일의 값은 빅 엔디언이다.
각 파일의 내용과 패딩은 테이블로 읽지 않는다. 엔트리의 START_OFS와 FILE_SIZE로 필요할 때 직접 읽는다.
"""


def read_header(br: BinaryReader) -> TRP_HEADER:
    return TRP_HEADER(
        SIGNATURE=br.read_struct(struct.Struct(">I"))[0],
        VERSION=br.read_struct(struct.Struct(">I"))[0],
        FILE_SIZE=br.read_struct(struct.Struct(">Q"))[0],
        FILE_COUNT=br.read_struct(struct.Struct(">I"))[0],
        ENTRY_SIZE=br.read_struct(struct.Struct(">I"))[0],
        DEV_FLAG=br.read_struct(struct.Struct(">I"))[0],
        HASH=br.read_bytes(20),
        PADDING=br.read_bytes(16),
    )


def read_entry_list(br: BinaryReader, file_count: int) -> list[TRP_FILE_ENTRY]:
    entry_list: list[TRP_FILE_ENTRY] = []
    for _ in range(file_count):
        entry_list.append(TRP_FILE_ENTRY(
            FILE_NAME=br.read_bytes(16),
            unknown_1=br.read_bytes(20),
            START_OFS=br.read_struct(struct.Struct(">I"))[0],
            unknown_2=br.read_struct(struct.Struct(">I"))[0],
            FILE_SIZE=br.read_struct(struct.Struct(">I"))[0],
            unknown_3=br.read_struct(struct.Struct(">I"))[0],
            PADDING=br.read_bytes(12),
        ))
    return entry_list
