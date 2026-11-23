from dataclasses import dataclass

from ymtools.src.structure._tables import TABLE_HEADER
from ymtools.src.typealias.ctype import uint16, uint32


@dataclass(slots=True)
class GOP_GFIN(TABLE_HEADER):
    VERSION: uint32
    unknown_1: uint32
    unknown_2: uint32
    unknown_3: uint32


@dataclass(slots=True)
class GMET_ITEM:
    KIND: uint16
    VALUE: uint16


@dataclass(slots=True)
class GMET_NODE:
    NAME_IDX: uint16
    ITEM_COUNT: uint16
    ITEM_LIST: list[GMET_ITEM]


@dataclass(slots=True)
class GOP_GMET(TABLE_HEADER):
    NODE_LIST: list[GMET_NODE]


@dataclass(slots=True)
class GREC_COLUMN:
    TYPE: uint32
    OFFSET: uint32
    NAME_IDX: uint16
    LANG_FLAG: uint16


@dataclass(slots=True)
class GOP_GREC(TABLE_HEADER):
    COLUMN_COUNT: uint32
    COLUMN_LIST: list[GREC_COLUMN]


@dataclass(slots=True)
class GOP_GDAT(TABLE_HEADER):
    RECORD_SIZE: uint32
    RECORD_COUNT: uint32
    INDEX_LIST_OFS: uint32
    RECORD_LIST_OFS: uint32
    INDEX_LIST: list[uint32]
    INDEX_LIST_PAD: bytes
    RECORD_LIST: list[bytes]
    GDAT_PAD: bytes
