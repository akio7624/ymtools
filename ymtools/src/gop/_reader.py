import struct

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.gop._tables import GENESTRT, GMET_ITEM, GMET_NODE, GOP_GDAT, GOP_GFIN, GOP_GMET, GOP_GREC, GREC_COLUMN
from ymtools.src.gop.exceptions import GopException

__all__ = ["read_table", "parse_gfin", "parse_gmet", "parse_grec", "parse_genestrt", "parse_gdat"]


"""
각 테이블은 16바이트 헤더(SIGNATURE, TABLE_SIZE)와 TABLE_SIZE 만큼의 Body로 이루어진다.
read_table()이 헤더를 읽고 Body를 통째로 바이트로 가져오며, parse_*() 함수들이 Body를 해석한다.
Body 안의 오프셋은 모두 Body의 시작점을 기준으로 한다.
패딩은 별도로 보관하지 않는다.
"""


def read_table(br: BinaryReader, file_size: int) -> tuple[bytes, bytes]:
    signature, table_size = br.read_struct(struct.Struct("<8sQ"))
    if table_size > file_size - br.tell():
        raise GopException(f"TABLE_SIZE of the table '{signature.decode('ascii', 'replace')}' ({table_size}) exceeds the rest of the file({file_size - br.tell()} bytes)")
    return signature, br.read_bytes(table_size)


def parse_gfin(body: bytes) -> GOP_GFIN:
    if len(body) < 16:
        raise GopException(f"GOP GFIN body is too short: {len(body)} bytes")
    version, unknown_1, unknown_2, unknown_3 = struct.unpack_from("<4I", body, 0)
    return GOP_GFIN(VERSION=version, unknown_1=unknown_1, unknown_2=unknown_2, unknown_3=unknown_3)


def parse_gmet(body: bytes) -> GOP_GMET:
    def read_node(ofs: int, parents: frozenset[int]) -> GMET_NODE:
        if ofs in parents:
            raise GopException(f"GOP GMET has a cycle at offset {ofs}")
        if ofs + 4 > len(body):
            raise GopException(f"GOP GMET node offset {ofs} is out of range(body size: {len(body)})")
        name_idx, item_count = struct.unpack_from("<HH", body, ofs)
        if ofs + 4 + (4 * item_count) > len(body):
            raise GopException(f"GOP GMET node at offset {ofs} has {item_count} item(s) but the body is too short")

        item_list: list[GMET_ITEM] = []
        for i in range(item_count):
            kind, value = struct.unpack_from("<HH", body, ofs + 4 + (4 * i))
            if kind == 0:
                item_list.append(GMET_ITEM(KIND=0, VALUE=value))
            elif kind == 1:
                item_list.append(GMET_ITEM(KIND=1, VALUE=value, CHILD=read_node(value, parents | {ofs})))
            else:
                raise GopException(f"GOP GMET item KIND must be 0 or 1, current: {kind} (node offset: {ofs})")
        return GMET_NODE(NAME_IDX=name_idx, ITEM_LIST=item_list)

    return GOP_GMET(ROOT=read_node(0, frozenset()))


def parse_grec(body: bytes) -> GOP_GREC:
    if len(body) < 4:
        raise GopException(f"GOP GREC body is too short: {len(body)} bytes")
    column_count = struct.unpack_from("<I", body, 0)[0]
    if 4 + (12 * column_count) > len(body):
        raise GopException(f"GOP GREC has {column_count} column(s) but the body is too short")

    column_list = [
        GREC_COLUMN(TYPE=type_id, OFFSET=offset, NAME_IDX=name_idx, LANG_FLAG=lang_flag)
        for type_id, offset, name_idx, lang_flag in struct.iter_unpack("<IIHH", body[4:4 + (12 * column_count)])
    ]
    return GOP_GREC(COLUMN_LIST=column_list)


def parse_genestrt(body: bytes) -> GENESTRT:
    if len(body) < 16:
        raise GopException(f"GENESTRT body is too short: {len(body)} bytes")
    string_count, string_ofs_list_ofs, string_list_ofs, _ = struct.unpack_from("<4I", body, 0)
    if string_ofs_list_ofs + (4 * (string_count + 1)) > len(body):
        raise GopException(f"GENESTRT has {string_count} string(s) but the offset list does not fit in the body")

    string_ofs_list = struct.unpack_from(f"<{string_count + 1}I", body, string_ofs_list_ofs)
    string_list: list[str] = []
    for i in range(string_count):
        start = string_list_ofs + string_ofs_list[i]
        end = body.find(b"\x00", start)
        if start >= len(body) or end == -1:
            raise GopException(f"GENESTRT string #{i} is not terminated within the body")
        try:
            string_list.append(body[start:end].decode("utf-8"))
        except UnicodeDecodeError as e:
            raise GopException(f"GENESTRT string #{i} is not valid UTF-8: {e}") from e
    return GENESTRT(STRING_LIST=string_list)


def parse_gdat(body: bytes) -> GOP_GDAT:
    if len(body) < 16:
        raise GopException(f"GOP GDAT body is too short: {len(body)} bytes")
    record_size, record_count, index_list_ofs, record_list_ofs = struct.unpack_from("<4I", body, 0)
    if record_size == 0 and record_count != 0:
        raise GopException(f"GOP GDAT RECORD_SIZE is 0 but RECORD_COUNT is {record_count}")
    if index_list_ofs + (4 * record_count) > len(body):
        raise GopException(f"GOP GDAT has {record_count} record(s) but the index list does not fit in the body")
    if record_list_ofs + (record_size * record_count) > len(body):
        raise GopException(f"GOP GDAT has {record_count} record(s) of {record_size} bytes but the record list does not fit in the body")

    index_list = list(struct.unpack_from(f"<{record_count}I", body, index_list_ofs))
    record_list = [body[record_list_ofs + (record_size * i):record_list_ofs + (record_size * (i + 1))] for i in range(record_count)]
    return GOP_GDAT(RECORD_SIZE=record_size, RECORD_COUNT=record_count, INDEX_LIST=index_list, RECORD_LIST=record_list)
