import struct

from ymtools.src.apkidx.structure._tables import GENESTRT
from ymtools.src.apkidx.structure.utils import get_align16_count
from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.gop._tables import GMET_ITEM, GMET_NODE, GOP_GDAT, GOP_GFIN, GOP_GMET, GOP_GREC, GREC_COLUMN

__all__ = ["read_gfin", "read_gmet", "read_grec", "read_genestrt", "read_gdat"]


"""
패딩은 별도로 테이블에 넣지 않는걸로 한다. 단 GENESTRT와 GDAT는 리스트 사이에 패딩이 있어 검증을 위해 따로 보관한다.
GENEEOF는 apk와 동일하므로 structure의 read_geneeof()를 그대로 사용한다.
"""


def read_gfin(br: BinaryReader) -> GOP_GFIN:
    return GOP_GFIN(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        VERSION=br.read_struct(struct.Struct("<I"))[0],
        unknown_1=br.read_struct(struct.Struct("<I"))[0],
        unknown_2=br.read_struct(struct.Struct("<I"))[0],
        unknown_3=br.read_struct(struct.Struct("<I"))[0],
    )


def read_gmet(br: BinaryReader) -> GOP_GMET:
    gmet_ofs = br.tell()
    br.seek(gmet_ofs + 8 + 8)

    # there is no node count, but the nodes are stored in DFS order so the children follow their parent
    node_list: list[GMET_NODE] = []

    def read_node() -> None:
        name_idx, item_count = br.read_struct(struct.Struct("<HH"))
        item_list = [GMET_ITEM(KIND=kind, VALUE=value) for kind, value in br.iter_struct(struct.Struct("<HH"), item_count)]
        node_list.append(GMET_NODE(NAME_IDX=name_idx, ITEM_COUNT=item_count, ITEM_LIST=item_list))
        for item in item_list:
            if item.KIND == 1:
                read_node()

    read_node()
    node_list_end = br.tell()

    # go to start of GMET
    br.seek(gmet_ofs)
    gmet = GOP_GMET(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        NODE_LIST=node_list,
    )
    br.seek(node_list_end)
    br.skip(get_align16_count(br.tell()))
    return gmet


def read_grec(br: BinaryReader) -> GOP_GREC:
    grec_ofs = br.tell()
    column_count_ofs = grec_ofs + 8 + 8
    column_list_ofs = grec_ofs + 8 + 8 + 4

    # read column_count first for iter_struct()
    br.seek(column_count_ofs)
    column_count = br.read_uint32()

    # then read column_list
    column_list: list[GREC_COLUMN] = []
    br.seek(column_list_ofs)
    for tp in br.iter_struct(struct.Struct("<IIHH"), column_count):
        TYPE, OFFSET, NAME_IDX, LANG_FLAG = tp

        column_list.append(GREC_COLUMN(
            TYPE=TYPE,
            OFFSET=OFFSET,
            NAME_IDX=NAME_IDX,
            LANG_FLAG=LANG_FLAG,
        ))

    # go to start of GREC
    br.seek(grec_ofs)
    grec = GOP_GREC(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        COLUMN_COUNT=br.read_struct(struct.Struct("<I"))[0],
        COLUMN_LIST=column_list,
    )
    br.skip(12 * grec.COLUMN_COUNT)
    br.skip(get_align16_count(br.tell()))
    return grec


def read_genestrt(br: BinaryReader) -> GENESTRT:
    genestrt_ofs = br.tell()
    string_count_ofs = genestrt_ofs + 8 + 8

    # read string_count first for iter_struct()
    br.seek(string_count_ofs)
    string_count = br.read_uint32()
    br.skip(4)
    string_list_ofs = genestrt_ofs + 8 + 8 + br.read_uint32()

    # parse string_ofs_list, unlike apk it has one more element for the size of string_list
    string_ofs_list_ofs = genestrt_ofs + 8 + 8 + 4 + 4 + 4 + 4
    br.seek(string_ofs_list_ofs)
    string_ofs_list = [x[0] for x in br.iter_struct(struct.Struct("<I"), string_count + 1)]
    string_ofs_list_pad = br.read_bytes(get_align16_count(br.tell()))

    # parse string_list
    string_list: list[str] = []
    br.seek(string_list_ofs)
    for _ in range(string_count):
        buf: bytearray = bytearray()
        while True:
            c: bytes = br.read_bytes(1)
            if c == b'\x00':
                break
            buf.extend(c)
        string_list.append(buf.decode("utf-8"))
    string_list_end = br.tell()
    string_list_pad = br.read_bytes(get_align16_count(string_list_end))

    br.seek(genestrt_ofs)
    genestrt = GENESTRT(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        STRING_COUNT=br.read_struct(struct.Struct("<I"))[0],
        STRING_OFS_LIST_OFS=br.read_struct(struct.Struct("<I"))[0],
        STRING_LIST_OFS=br.read_struct(struct.Struct("<I"))[0],
        TABLE_SIZE_2=br.read_struct(struct.Struct("<I"))[0],
        STRING_OFS_LIST=string_ofs_list,
        STRING_OFS_LIST_PAD=string_ofs_list_pad,
        STRING_LIST=string_list,
        STRING_LIST_PAD=string_list_pad,
    )
    br.seek(string_list_end + len(string_list_pad))  # skip STRING_LIST and its padding
    return genestrt


def read_gdat(br: BinaryReader) -> GOP_GDAT:
    gdat_ofs = br.tell()
    record_size_ofs = gdat_ofs + 8 + 8

    # read the sizes and offsets first for the lists
    br.seek(record_size_ofs)
    record_size = br.read_uint32()
    record_count = br.read_uint32()
    index_list_ofs = gdat_ofs + 8 + 8 + br.read_uint32()
    record_list_ofs = gdat_ofs + 8 + 8 + br.read_uint32()

    # parse index_list
    br.seek(index_list_ofs)
    index_list = [x[0] for x in br.iter_struct(struct.Struct("<I"), record_count)]
    index_list_pad = br.read_bytes(get_align16_count(br.tell()))

    # parse record_list
    br.seek(record_list_ofs)
    records = br.read_bytes(record_size * record_count)
    record_list = [records[i * record_size:(i + 1) * record_size] for i in range(record_count)]
    record_list_end = br.tell()
    gdat_pad = br.read_bytes(get_align16_count(record_list_end))

    br.seek(gdat_ofs)
    gdat = GOP_GDAT(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        RECORD_SIZE=br.read_struct(struct.Struct("<I"))[0],
        RECORD_COUNT=br.read_struct(struct.Struct("<I"))[0],
        INDEX_LIST_OFS=br.read_struct(struct.Struct("<I"))[0],
        RECORD_LIST_OFS=br.read_struct(struct.Struct("<I"))[0],
        INDEX_LIST=index_list,
        INDEX_LIST_PAD=index_list_pad,
        RECORD_LIST=record_list,
        GDAT_PAD=gdat_pad,
    )
    br.seek(record_list_end + len(gdat_pad))  # skip RECORD_LIST and its padding
    return gdat
