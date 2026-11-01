import struct

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.structure._tables import ENDILTLE, GENEEOF, GENESTRT, PACKFSLS, PACKHEDR, PACKTOC, TOC_SEGMENT, FS_SEGMENT
from ymtools.src.structure.utils import get_align16_count

__all__ = ["read_endiltle", "read_packhedr", "read_packtoc", "read_packfsls", "read_genestrt", "read_geneeof"]


"""
패딩은 별도로 테이블에 넣지 않는걸로 한다.
만약 패딩이 잘못되었더라도 검증단계에서 예상되는 패딩크기만큼 건너뛴 후 나오는 다음 테이블 검사에서 확인이 가능하며
현재 파싱 구조상 리스트가 있는 경우 인스턴스 생성 전 로드해서 초기화하고 리스트 부분은 skip하는데 패딩을 데이터 클래스 안에 넣으면
스킵하는 부분 처리하기가 곤란함
"""


def read_endiltle(br: BinaryReader) -> ENDILTLE:
    return ENDILTLE(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0]
    )


def read_packhedr(br: BinaryReader) -> PACKHEDR:
    return PACKHEDR(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        unknown_1=br.read_struct(struct.Struct("<I"))[0],
        NAME_IDX=br.read_struct(struct.Struct("<I"))[0],
        ROOT_FILES_OFS=br.read_struct(struct.Struct("<I"))[0],
        FS_PAD_TYPE=br.read_struct(struct.Struct("<I"))[0],
        HASH=br.read_struct(struct.Struct("<16s"))[0],
    )


def read_packtoc(br: BinaryReader) -> PACKTOC:
    packtoc_ofs = br.tell()
    toc_seg_count_ofs = packtoc_ofs + 8 + 8 + 4
    toc_seg_list_ofs = packtoc_ofs + 8 + 8 + 4 + 4 + 4 + 4

    # read toc_seg_count first for iter_struct()
    br.seek(toc_seg_count_ofs)
    toc_seg_count = br.read_uint32()

    # then read toc_seg_list
    toc_seg_list: list[TOC_SEGMENT] = []
    br.seek(toc_seg_list_ofs)
    for tp in br.iter_struct(struct.Struct("<ccHIIIQQQ"), toc_seg_count):
        IDENTIFIER, COMPRESS_TYPE, unknown_1, NAME_IDX, PACKAGE_NAME_IDX, unknown_2, field1, field2, field3 = tp

        toc_seg_list.append(TOC_SEGMENT(
            IDENTIFIER=int.from_bytes(IDENTIFIER),
            COMPRESS_TYPE=int.from_bytes(COMPRESS_TYPE),
            unknown_1=unknown_1,
            NAME_IDX=NAME_IDX,
            PACKAGE_NAME_IDX=PACKAGE_NAME_IDX,
            unknown_2=unknown_2,
            # for directory
            ENTRY_INDEX=field1 & 0xFFFFFFFF,
            ENTRY_COUNT=(field1 >> 32) & 0xFFFFFFFF,
            unused_1=field2,
            unused_2=field3,
            # for file
            FILE_ABSOLUTE_OFS=field1,
            FILE_SIZE=field2,
            FILE_ZSIZE=field3,
        ))

    # go to start of PACKTOC
    br.seek(packtoc_ofs)
    packtoc = PACKTOC(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        TOC_SEG_SIZE=br.read_struct(struct.Struct("<I"))[0],
        TOC_SEG_COUNT=br.read_struct(struct.Struct("<I"))[0],
        TOC_SEG_LIST_OFS=br.read_struct(struct.Struct("<I"))[0],
        unknown_1=br.read_struct(struct.Struct("<I"))[0],
        TOC_SEG_LIST=toc_seg_list
    )
    br.skip(packtoc.TOC_SEG_SIZE * packtoc.TOC_SEG_COUNT)
    br.skip(get_align16_count(br.tell()))
    return packtoc


def read_packfsls(br: BinaryReader) -> PACKFSLS:
    packfsls_ofs = br.tell()
    fs_seg_count_ofs = packfsls_ofs + 8 + 8
    fs_seg_list_ofs = packfsls_ofs + 8 + 8 + 4 + 4 + 4 + 4

    # read fs_seg_count first for iter_struct()
    br.seek(fs_seg_count_ofs)
    fs_seg_count = br.read_uint32()

    # then read fs_seg_list
    fs_seg_list: list[FS_SEGMENT] = []
    br.seek(fs_seg_list_ofs)
    for tp in br.iter_struct(struct.Struct("<IIQQ16s"), fs_seg_count):
        NAME_IDX, PACKAGE_NAME_IDX, FS_ABSOLUTE_OFS, FS_SIZE, FS_HASH = tp

        fs_seg_list.append(FS_SEGMENT(
            NAME_IDX=NAME_IDX,
            PACKAGE_NAME_IDX=PACKAGE_NAME_IDX,
            FS_ABSOLUTE_OFS=FS_ABSOLUTE_OFS,
            FS_SIZE=FS_SIZE,
            FS_HASH=FS_HASH,
        ))

    # go to start of PACKFSLS
    br.seek(packfsls_ofs)
    packfsls = PACKFSLS(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
        FS_SEG_COUNT=br.read_struct(struct.Struct("<I"))[0],
        FS_SEG_SIZE=br.read_struct(struct.Struct("<I"))[0],
        FS_SEG_LIST_OFS=br.read_struct(struct.Struct("<I"))[0],
        unknown_1=br.read_struct(struct.Struct("<I"))[0],
        FS_SEG_LIST=fs_seg_list,
    )
    br.skip(packfsls.FS_SEG_SIZE * packfsls.FS_SEG_COUNT)
    br.skip(get_align16_count(br.tell()))
    return packfsls


def read_genestrt(br: BinaryReader) -> GENESTRT:
    genestrt_ofs = br.tell()
    string_count_ofs = genestrt_ofs + 8 + 8

    # read string_count first for iter_struct()
    br.seek(string_count_ofs)
    string_count = br.read_uint32()
    br.skip(4)
    string_list_ofs = genestrt_ofs + 8 + 8 + br.read_uint32()

    # parse string_ofs_list
    string_ofs_list_ofs = genestrt_ofs + 8 + 8 + 4 + 4 + 4 + 4
    br.seek(string_ofs_list_ofs)
    string_ofs_list = [x[0] for x in br.iter_struct(struct.Struct("<I"), string_count)]
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


def read_geneeof(br: BinaryReader) -> GENEEOF:
    return GENEEOF(
        SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
        TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0]
    )
