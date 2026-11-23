from dataclasses import dataclass, field

from ymtools.src.typealias.ctype import uint16, uint32


@dataclass(slots=True)
class GOP_GFIN:
    VERSION: uint32
    unknown_1: uint32
    unknown_2: uint32
    unknown_3: uint32


@dataclass(slots=True)
class GMET_ITEM:
    KIND: uint16  # 0: value(string index of GENESTRT), 1: child node
    VALUE: uint16  # KIND=0: string index, KIND=1: offset of the child node from the start of the table body
    CHILD: "GMET_NODE | None" = None  # resolved child node (KIND=1 only)


@dataclass(slots=True)
class GMET_NODE:
    NAME_IDX: uint16
    ITEM_LIST: list[GMET_ITEM] = field(default_factory=list)


@dataclass(slots=True)
class GOP_GMET:
    ROOT: GMET_NODE


@dataclass(slots=True)
class GREC_COLUMN:
    TYPE: uint32
    OFFSET: uint32
    NAME_IDX: uint16
    LANG_FLAG: uint16


@dataclass(slots=True)
class GOP_GREC:
    COLUMN_LIST: list[GREC_COLUMN]


@dataclass(slots=True)
class GENESTRT:
    STRING_LIST: list[str]


@dataclass(slots=True)
class GOP_GDAT:
    RECORD_SIZE: uint32
    RECORD_COUNT: uint32
    INDEX_LIST: list[uint32]
    RECORD_LIST: list[bytes]  # raw bytes of each record, decoded with the column information of GREC
