from dataclasses import dataclass

from ymtools.src.typealias.ctype import uchar, uint16, uint32, uint64


@dataclass(slots=True)
class TABLE_HEADER:
    SIGNATURE: bytes
    TABLE_SIZE: uint64


@dataclass(slots=True)
class ENDILTLE(TABLE_HEADER):
    pass


@dataclass(slots=True)
class PACKHEDR(TABLE_HEADER):
    unknown_1: uint32
    NAME_IDX: uint32
    ROOT_FILES_OFS: uint32
    FS_PAD_TYPE: uint32
    HASH: bytes


@dataclass(slots=True)
class TOC_SEGMENT:
    IDENTIFIER: uchar
    COMPRESS_TYPE: uchar
    unknown_1: uint16
    NAME_IDX: uint32
    PACKAGE_NAME_IDX: uint32
    unknown_2: uint32
    ENTRY_INDEX: uint32 = 0
    ENTRY_COUNT: uint32 = 0
    unused_1: uint64 = 0
    unused_2: uint64 = 0
    FILE_ABSOLUTE_OFS: uint64 = 0
    FILE_SIZE: uint64 = 0
    FILE_ZSIZE: uint64 = 0


@dataclass(slots=True)
class PACKTOC(TABLE_HEADER):
    TOC_SEG_SIZE: uint32
    TOC_SEG_COUNT: uint32
    TOC_SEG_LIST_OFS: uint32
    unknown_1: uint32
    TOC_SEG_LIST: list[TOC_SEGMENT]


@dataclass(slots=True)
class FS_SEGMENT:
    NAME_IDX: uint32
    PACKAGE_NAME_IDX: uint32
    FS_ABSOLUTE_OFS: uint64
    FS_SIZE: uint64
    FS_HASH: bytes


@dataclass(slots=True)
class PACKFSLS(TABLE_HEADER):
    FS_SEG_COUNT: uint32
    FS_SEG_SIZE: uint32
    FS_SEG_LIST_OFS: uint32
    unknown_1: uint32
    FS_SEG_LIST: list[FS_SEGMENT]


@dataclass(slots=True)
class GENESTRT(TABLE_HEADER):
    STRING_COUNT: uint32
    STRING_OFS_LIST_OFS: uint32
    STRING_LIST_OFS: uint32
    TABLE_SIZE_2: uint32
    STRING_OFS_LIST: list[uint32]
    STRING_LIST: list[str]


@dataclass(slots=True)
class GENEEOF(TABLE_HEADER):
    pass


@dataclass(slots=True)
class FS_FILE_SEG:
    NAME_IDX: uint32
    COMPRESS_TYPE: uchar
    unknown_1: uchar
    unknown_2: uchar
    unknown_3: uchar
    FILE_OFS: uint64
    FILE_SIZE: uint64
    FILE_ZSIZE: uint64


@dataclass(slots=True)
class PACKFSHD(TABLE_HEADER):
    unknown_1: uint32
    FILE_SEG_SIZE: uint32
    FILE_SEG_COUNT: uint32
    FS_FILE_SEG_LIST_OFS: uint32
    GENEEOF_OFS: uint32
    unknown_2: uint32
    unknown_3: uint32
    unknown_4: uint32
    FS_FILE_SEG_LIST: list[FS_FILE_SEG]


@dataclass(slots=True)
class FILE_SET:
    SEGMENT: FS_SEGMENT
    FS_ENDILTLE: ENDILTLE
    FS_PACKFSHD: PACKFSHD
    FS_GENESTRT: GENESTRT
    FS_GENEEOF: GENEEOF
