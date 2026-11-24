from io import BytesIO

from ymtools.src.trp._tables import TRP_FILE_ENTRY, TRP_HEADER

__all__ = ["make_header", "make_entry_list"]


"""
주어진 테이블 객체를 실제 바이너리로 변환한다
여기 넘어오는 객체는 지연 계산이 필요한 필드들의 계산이 완료된 것들이어야함
trp 파일의 값은 빅 엔디언이다
"""


def make_header(obj: TRP_HEADER) -> bytes:
    table: BytesIO = BytesIO()
    assert obj.SIGNATURE == 0xDCA24D00

    table.write(obj.SIGNATURE.to_bytes(4, byteorder="big"))
    table.write(obj.VERSION.to_bytes(4, byteorder="big"))
    table.write(obj.FILE_SIZE.to_bytes(8, byteorder="big"))
    table.write(obj.FILE_COUNT.to_bytes(4, byteorder="big"))
    table.write(obj.ENTRY_SIZE.to_bytes(4, byteorder="big"))
    table.write(obj.DEV_FLAG.to_bytes(4, byteorder="big"))
    table.write(obj.HASH)
    table.write(obj.PADDING)

    return table.getvalue()


def make_entry_list(obj: list[TRP_FILE_ENTRY]) -> bytes:
    table: BytesIO = BytesIO()

    for entry in obj:
        table.write(entry.FILE_NAME)
        table.write(entry.unknown_1)
        table.write(entry.START_OFS.to_bytes(4, byteorder="big"))
        table.write(entry.unknown_2.to_bytes(4, byteorder="big"))
        table.write(entry.FILE_SIZE.to_bytes(4, byteorder="big"))
        table.write(entry.unknown_3.to_bytes(4, byteorder="big"))
        table.write(entry.PADDING)

    return table.getvalue()
