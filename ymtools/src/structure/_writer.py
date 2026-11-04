from io import BytesIO
import struct

from ymtools.src.structure._tables import ENDILTLE, GENEEOF, GENESTRT, PACKFSHD, PACKFSLS, PACKHEDR, PACKTOC, TOC_SEGMENT, FS_SEGMENT
from ymtools.src.structure.utils import get_align16_count


"""
주어진 테이블 객체를 실제 바이너리로 변환한다
여기 넘어오는 객체는 지연 계산이 필요한 필드들의 계산이 완료된 것들이어야함
"""


def make_endiltle(obj: ENDILTLE) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == b"ENDILTLE"
    table.write(obj.SIGNATURE)
    table.write(obj.TABLE_SIZE.to_bytes(8, byteorder="little"))

    return table.getvalue()


def make_packhedr(obj: PACKHEDR) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == b"PACKHEDR"

    table.write(obj.SIGNATURE)
    table.write(obj.TABLE_SIZE.to_bytes(8, byteorder="little"))
    table.write(obj.unknown_1.to_bytes(4, byteorder="little"))
    table.write(obj.NAME_IDX.to_bytes(4, byteorder="little"))
    table.write(obj.ROOT_FILES_OFS.to_bytes(4, byteorder="little"))
    table.write(obj.FS_PAD_TYPE.to_bytes(4, byteorder="little"))
    table.write(obj.HASH)

    return table.getvalue()


def make_packtoc(obj: PACKTOC) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == b"PACKTOC "

    table.write(obj.SIGNATURE)
    table.write(obj.TABLE_SIZE.to_bytes(8, byteorder="little"))
    table.write(obj.TOC_SEG_SIZE.to_bytes(4, byteorder="little"))
    table.write(obj.TOC_SEG_COUNT.to_bytes(4, byteorder="little"))
    table.write(obj.TOC_SEG_LIST_OFS.to_bytes(4, byteorder="little"))
    table.write(obj.unknown_1.to_bytes(4, byteorder="little"))

    for seg in obj.TOC_SEG_LIST:
        table.write(seg.IDENTIFIER.to_bytes(1, byteorder="little"))
        table.write(seg.COMPRESS_TYPE.to_bytes(1, byteorder="little"))
        table.write(seg.unknown_1.to_bytes(2, byteorder="little"))
        table.write(seg.NAME_IDX.to_bytes(4, byteorder="little"))
        table.write(seg.PACKAGE_NAME_IDX.to_bytes(4, byteorder="little"))
        table.write(seg.unknown_2.to_bytes(4, byteorder="little"))

        if seg.IDENTIFIER == 1:
            table.write(seg.ENTRY_INDEX.to_bytes(4, byteorder="little"))
            table.write(seg.ENTRY_COUNT.to_bytes(4, byteorder="little"))
            table.write(seg.unused_1.to_bytes(8, byteorder="little"))
            table.write(seg.unused_2.to_bytes(8, byteorder="little"))
        elif seg.IDENTIFIER == 0:
            table.write(seg.FILE_ABSOLUTE_OFS.to_bytes(8, byteorder="little"))
            table.write(seg.FILE_SIZE.to_bytes(8, byteorder="little"))
            table.write(seg.FILE_ZSIZE.to_bytes(8, byteorder="little"))

    table.write(bytes(get_align16_count(table.tell())))

    return table.getvalue()


def make_packfsls(obj: PACKFSLS) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == b"PACKFSLS"

    table.write(obj.SIGNATURE)
    table.write(obj.TABLE_SIZE.to_bytes(8, byteorder="little"))
    table.write(obj.FS_SEG_COUNT.to_bytes(4, byteorder="little"))
    table.write(obj.FS_SEG_SIZE.to_bytes(4, byteorder="little"))
    table.write(obj.FS_SEG_LIST_OFS.to_bytes(4, byteorder="little"))
    table.write(obj.unknown_1.to_bytes(4, byteorder="little"))

    for seg in obj.FS_SEG_LIST:
        table.write(seg.NAME_IDX.to_bytes(4, byteorder="little"))
        table.write(seg.PACKAGE_NAME_IDX.to_bytes(4, byteorder="little"))
        table.write(seg.FS_ABSOLUTE_OFS.to_bytes(8, byteorder="little"))
        table.write(seg.FS_SIZE.to_bytes(8, byteorder="little"))
        table.write(seg.FS_HASH)

    table.write(bytes(get_align16_count(table.tell())))

    return table.getvalue()


def make_genestrt(obj: GENESTRT) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == b"GENESTRT"

    table.write(obj.SIGNATURE)
    table.write(obj.TABLE_SIZE.to_bytes(8, byteorder="little"))
    table.write(obj.STRING_COUNT.to_bytes(4, byteorder="little"))
    table.write(obj.STRING_OFS_LIST_OFS.to_bytes(4, byteorder="little"))
    table.write(obj.STRING_LIST_OFS.to_bytes(4, byteorder="little"))
    table.write(obj.TABLE_SIZE_2.to_bytes(4, byteorder="little"))

    for ofs in obj.STRING_OFS_LIST:
        table.write(ofs.to_bytes(4, byteorder="little"))
    table.write(obj.STRING_OFS_LIST_PAD)

    for s in obj.STRING_LIST:
        table.write(s.encode("utf-8") + b"\x00")
    table.write(obj.STRING_LIST_PAD)

    return table.getvalue()


def make_geneeof(obj: GENEEOF) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == b"GENEEOF "

    table.write(obj.SIGNATURE)
    table.write(obj.TABLE_SIZE.to_bytes(8, byteorder="little"))

    return table.getvalue()


def make_packfshd(obj: PACKFSHD) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == b"PACKFSHD"

    table.write(obj.SIGNATURE)
    table.write(obj.TABLE_SIZE.to_bytes(8, byteorder="little"))
    table.write(obj.unknown_1.to_bytes(4, byteorder="little"))
    table.write(obj.FILE_SEG_SIZE.to_bytes(4, byteorder="little"))
    table.write(obj.FILE_SEG_COUNT.to_bytes(4, byteorder="little"))
    table.write(obj.FS_FILE_SEG_LIST_OFS.to_bytes(4, byteorder="little"))
    table.write(obj.GENEEOF_OFS.to_bytes(4, byteorder="little"))
    table.write(obj.unknown_2.to_bytes(4, byteorder="little"))
    table.write(obj.unknown_3.to_bytes(4, byteorder="little"))
    table.write(obj.unknown_4.to_bytes(4, byteorder="little"))

    for seg in obj.FS_FILE_SEG_LIST:
        table.write(seg.NAME_IDX.to_bytes(4, byteorder="little"))
        table.write(seg.COMPRESS_TYPE.to_bytes(1, byteorder="little"))
        table.write(seg.unknown_1.to_bytes(1, byteorder="little"))
        table.write(seg.unknown_2.to_bytes(1, byteorder="little"))
        table.write(seg.unknown_3.to_bytes(1, byteorder="little"))
        table.write(seg.FILE_OFS.to_bytes(8, byteorder="little"))
        table.write(seg.FILE_SIZE.to_bytes(8, byteorder="little"))
        table.write(seg.FILE_ZSIZE.to_bytes(8, byteorder="little"))

    table.write(bytes(get_align16_count(table.tell())))

    return table.getvalue()
