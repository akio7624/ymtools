import logging
import math
import struct
from pathlib import Path

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.structure._tables import ENDILTLE, FILE_SET, GENEEOF, GENESTRT, PACKFSHD, PACKFSLS, PACKHEDR, PACKTOC, TOC_SEGMENT, FS_FILE_SEG, FS_SEGMENT
from ymtools.src.structure.utils import get_align16_count

__all__ = ["APK"]
log = logging.getLogger(__name__)


"""
패딩은 별도로 테이블에 넣지 않는걸로 한다.
만약 패딩이 잘못되었더라도 검증단계에서 예상되는 패딩크기만큼 건너뛴 후 나오는 다음 테이블 검사에서 확인이 가능하며
현재 파싱 구조상 리스트가 있는 경우 인스턴스 생성 전 로드해서 초기화하고 리스트 부분은 skip하는데 패딩을 데이터 클래스 안에 넣으면
스킵하는 부분 처리하기가 곤란함
"""


class APK:
    def __init__(
        self,
        endiltle: ENDILTLE,
        packhedr: PACKHEDR,
        packtoc: PACKTOC,
        packfsls: PACKFSLS,
        genestrt: GENESTRT,
        geneeof: GENEEOF,
        file_sets: list[FILE_SET],
    ) -> None:
        self._ENDILTLE = endiltle
        self._PACKHEDR = packhedr
        self._PACKTOC = packtoc
        self._PACKFSLS = packfsls
        self._GENESTRT = genestrt
        self._GENEEOF = geneeof
        self._FILE_SETS = file_sets

    @classmethod
    def read_apk(cls, path: Path) -> "APK":
        log.info(f"reading APK: {path}")

        with BinaryReader(path) as br:
            # ====================== ENDILTLE ======================
            log.info(f"Processing table ENDILTLE")
            endiltle = ENDILTLE(
                SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
                TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0]
            )

            # ====================== PACKHEDR ======================
            log.info(f"Processing table PACKHEDR")
            packhedr = PACKHEDR(
                SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
                TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
                unknown_1=br.read_struct(struct.Struct("<I"))[0],
                NAME_IDX=br.read_struct(struct.Struct("<I"))[0],
                ROOT_FILES_OFS=br.read_struct(struct.Struct("<I"))[0],
                FS_PAD_TYPE=br.read_struct(struct.Struct("<I"))[0],
                HASH=br.read_struct(struct.Struct("<16s"))[0],
            )

            # ====================== PACKTOC ======================
            log.info(f"Processing table PACKTOC")
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

            # ====================== PACKFSLS ======================
            log.info(f"Processing table PACKFSLS")
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

            # ====================== GENESTRT ======================
            log.info(f"Processing table GENESTRT")
            genestrt = cls._read_genestrt(br)

            # ====================== GENEEOF ======================
            log.info(f"Processing table GENEEOF")
            geneeof = GENEEOF(
                SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
                TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0]
            )

            # ====================== File Set List ======================
            file_sets: list[FILE_SET] = []
            for i, fs_seg in enumerate(packfsls.FS_SEG_LIST):
                log.info(f"Processing FILE_SET[{i}]")
                br.seek(fs_seg.FS_ABSOLUTE_OFS)

                # ---------------------- ENDILTLE ----------------------
                fs_endiltle = ENDILTLE(
                    SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
                    TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0]
                )

                # ---------------------- PACKFSHD ----------------------
                packfshd_ofs = br.tell()
                file_seg_count_ofs = packfshd_ofs + 8 + 8 + 4 + 4
                fs_file_seg_list_ofs = packfshd_ofs + 8 + 8 + 4 + 4 + 4 + 4 + 4 + 4 + 4 + 4

                # read file_seg_count first for iter_struct()
                br.seek(file_seg_count_ofs)
                file_seg_count = br.read_uint32()

                # then read fs_file_seg_list
                fs_file_seg_list: list[FS_FILE_SEG] = []
                br.seek(fs_file_seg_list_ofs)
                for tp in br.iter_struct(struct.Struct("<IccccQQQ"), file_seg_count):
                    NAME_IDX, COMPRESS_TYPE, unknown_1, unknown_2, unknown_3, FILE_OFS, FILE_SIZE, FILE_ZSIZE = tp

                    fs_file_seg_list.append(FS_FILE_SEG(
                        NAME_IDX=NAME_IDX,
                        COMPRESS_TYPE=int.from_bytes(COMPRESS_TYPE),
                        unknown_1=int.from_bytes(unknown_1),
                        unknown_2=int.from_bytes(unknown_2),
                        unknown_3=int.from_bytes(unknown_3),
                        FILE_OFS=FILE_OFS,
                        FILE_SIZE=FILE_SIZE,
                        FILE_ZSIZE=FILE_ZSIZE,
                    ))

                # go to start of PACKFSHD
                br.seek(packfshd_ofs)
                fs_packfshd = PACKFSHD(
                    SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
                    TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0],
                    unknown_1=br.read_struct(struct.Struct("<I"))[0],
                    FILE_SEG_SIZE=br.read_struct(struct.Struct("<I"))[0],
                    FILE_SEG_COUNT=br.read_struct(struct.Struct("<I"))[0],
                    FS_FILE_SEG_LIST_OFS=br.read_struct(struct.Struct("<I"))[0],
                    GENEEOF_OFS=br.read_struct(struct.Struct("<I"))[0],
                    unknown_2=br.read_struct(struct.Struct("<I"))[0],
                    unknown_3=br.read_struct(struct.Struct("<I"))[0],
                    unknown_4=br.read_struct(struct.Struct("<I"))[0],
                    FS_FILE_SEG_LIST=fs_file_seg_list,
                )
                br.skip(fs_packfshd.FILE_SEG_SIZE * fs_packfshd.FILE_SEG_COUNT)
                br.skip(get_align16_count(br.tell()))

                # ---------------------- GENESTRT ----------------------
                fs_genestrt = cls._read_genestrt(br)

                # ---------------------- GENEEOF ----------------------
                fs_geneeof = GENEEOF(
                    SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
                    TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0]
                )

                file_sets.append(FILE_SET(
                    SEGMENT=fs_seg,
                    FS_ENDILTLE=fs_endiltle,
                    FS_PACKFSHD=fs_packfshd,
                    FS_GENESTRT=fs_genestrt,
                    FS_GENEEOF=fs_geneeof,
                ))

        apk = cls(
            endiltle=endiltle,
            packhedr=packhedr,
            packtoc=packtoc,
            packfsls=packfsls,
            genestrt=genestrt,
            geneeof=geneeof,
            file_sets=file_sets
        )

        violations = apk.validate()
        if violations:
            log.error(f"APK validation failed: {len(violations)} violation(s)")
            for v in violations:
                log.error(f"  {v}")
            raise ApkException(violations)
        log.info("APK validation PASS!")

        return apk

    @staticmethod
    def _read_genestrt(br: BinaryReader) -> GENESTRT:
        """Read the GENESTRT table that starts at the current position. The reader is left right after the table."""
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

    def _align16_size(self, n: int) -> int:
        return math.ceil(n / 16) * 16

    def _sig(self, signature: bytes) -> str:
        return "".join(chr(c) if 32 <= c < 127 else f"\\x{c:02x}" for c in signature)

    def validate(self) -> list[str]:
        violations: list[str] = []

        # check for ENDILTLE
        violations += self._validate_endiltle(self._ENDILTLE, "ENDILTLE")

        # check for PACKHEDR
        if self._PACKHEDR.SIGNATURE != b"PACKHEDR":
            violations.append(f"PACKHEDR.SIGNATURE must be 'PACKHEDR', current: '{self._sig(self._PACKHEDR.SIGNATURE)}'")
        else:
            if self._PACKHEDR.TABLE_SIZE != 32:
                violations.append(f"Size of PACKHEDR table must be 32, current: {self._PACKHEDR.TABLE_SIZE}")
            if self._PACKHEDR.unknown_1 != 65536:
                violations.append(f"Value of PACKHEDR.unknown_1 must be 65536, current: {self._PACKHEDR.unknown_1}")
            if self._PACKHEDR.NAME_IDX != 0:
                log.warning("Value of PACKHEDR.NAME_IDX may be 0")
            if self._PACKHEDR.FS_PAD_TYPE not in [1, 2]:
                violations.append(f"Value of PACKHEDR.FS_PAD_TYPE may be 1 or 2, current: {self._PACKHEDR.FS_PAD_TYPE}")

        # check for PACKTOC
        if self._PACKTOC.SIGNATURE != b"PACKTOC ":
            violations.append(f"PACKTOC.SIGNATURE must be 'PACKTOC ', current: '{self._sig(self._PACKTOC.SIGNATURE)}'")
        else:
            expected_table_size = self._align16_size(4 + 4 + 4 + 4 + (self._PACKTOC.TOC_SEG_SIZE * self._PACKTOC.TOC_SEG_COUNT))
            if self._PACKTOC.TABLE_SIZE != expected_table_size:
                violations.append(f"Size of PACKTOC table must be {expected_table_size}, current: {self._PACKTOC.TABLE_SIZE}")
            if self._PACKTOC.TOC_SEG_SIZE != 40:
                violations.append(f"Size of PACKTOC.TOC_SEG_SIZE must be 40, current: {self._PACKTOC.TOC_SEG_SIZE}")
            if self._PACKTOC.TOC_SEG_LIST_OFS != 16:
                violations.append(f"Offset of PACKTOC.TOC_SEG_LIST_OFS must be 16, current: {self._PACKTOC.TOC_SEG_LIST_OFS}")
            if self._PACKTOC.unknown_1 != 0:
                log.warning(f"Value of PACKTOC.unknown_1 may be 0")
            if len(self._PACKTOC.TOC_SEG_LIST) != self._PACKTOC.TOC_SEG_COUNT:
                violations.append(f"Length of PACKTOC.TOC_SEG_LIST must be {self._PACKTOC.TOC_SEG_COUNT}, current: {len(self._PACKTOC.TOC_SEG_LIST)}")
            violations += self._validate_toc_segments()
            violations += self._validate_toc_order()

        # check for PACKFSLS
        if self._PACKFSLS.SIGNATURE != b"PACKFSLS":
            violations.append(f"PACKFSLS.SIGNATURE must be 'PACKFSLS', current: '{self._sig(self._PACKFSLS.SIGNATURE)}'")
        else:
            expected_table_size = self._align16_size(4 + 4 + 4 + 4 + (self._PACKFSLS.FS_SEG_SIZE * self._PACKFSLS.FS_SEG_COUNT))
            if self._PACKFSLS.TABLE_SIZE != expected_table_size:
                violations.append(f"Size of PACKFSLS table must be {expected_table_size}, current: {self._PACKFSLS.TABLE_SIZE}")
            if self._PACKFSLS.FS_SEG_SIZE != 40:
                violations.append(f"Size of PACKFSLS.FS_SEG_SIZE must be 40, current: {self._PACKFSLS.FS_SEG_SIZE}")
            if self._PACKFSLS.FS_SEG_LIST_OFS != 16:
                violations.append(f"Offset of PACKFSLS.FS_SEG_LIST_OFS must be 16, current: {self._PACKFSLS.FS_SEG_LIST_OFS}")
            if self._PACKFSLS.unknown_1 != 0:
                log.warning("Value of PACKFSLS.unknown_1 may be 0")
            if len(self._PACKFSLS.FS_SEG_LIST) != self._PACKFSLS.FS_SEG_COUNT:
                violations.append(f"Length of PACKFSLS.FS_SEG_LIST must be {self._PACKFSLS.FS_SEG_COUNT}, current: {len(self._PACKFSLS.FS_SEG_LIST)}")
            violations += self._validate_fs_segments()

        # check for GENESTRT
        violations += self._validate_genestrt(self._GENESTRT, "GENESTRT")

        # check for GENEEOF
        violations += self._validate_geneeof(self._GENEEOF, "GENEEOF")

        # check for File Sets
        violations += self._validate_file_sets()

        return violations

    def _validate_endiltle(self, endiltle: ENDILTLE, name: str) -> list[str]:
        violations: list[str] = []
        if endiltle.SIGNATURE != b"ENDILTLE":
            violations.append(f"{name}.SIGNATURE must be 'ENDILTLE', current: '{self._sig(endiltle.SIGNATURE)}'")
        else:
            if endiltle.TABLE_SIZE != 0:
                violations.append(f"Size of {name} table must be 0, current: {endiltle.TABLE_SIZE}")
        return violations

    def _validate_genestrt(self, genestrt: GENESTRT, name: str) -> list[str]:
        violations: list[str] = []
        if genestrt.SIGNATURE != b"GENESTRT":
            violations.append(f"{name}.SIGNATURE must be 'GENESTRT', current: '{self._sig(genestrt.SIGNATURE)}'")
        else:
            string_list_size = sum(len(s.encode("utf-8")) + 1 for s in genestrt.STRING_LIST)  # +1 for null
            string_list_ofs = self._align16_size(4 + 4 + 4 + 4 + (4 * genestrt.STRING_COUNT))
            expected_table_size = self._align16_size(string_list_ofs + string_list_size)

            if genestrt.TABLE_SIZE != expected_table_size:
                violations.append(f"Size of {name} table must be {expected_table_size}, current: {genestrt.TABLE_SIZE}")
            if genestrt.STRING_OFS_LIST_OFS != 16:
                violations.append(f"Offset of {name}.STRING_OFS_LIST_OFS must be 16, current: {genestrt.STRING_OFS_LIST_OFS}")
            if genestrt.STRING_LIST_OFS != string_list_ofs:
                violations.append(f"Offset of {name}.STRING_LIST_OFS must be {string_list_ofs}, current: {genestrt.STRING_LIST_OFS}")
            if genestrt.TABLE_SIZE_2 != genestrt.TABLE_SIZE:
                log.warning("Value of %s.TABLE_SIZE_2 may be equal to TABLE_SIZE(%d), current: %d", name, genestrt.TABLE_SIZE, genestrt.TABLE_SIZE_2)
            if len(genestrt.STRING_OFS_LIST) != genestrt.STRING_COUNT:
                violations.append(f"Length of {name}.STRING_OFS_LIST must be {genestrt.STRING_COUNT}, current: {len(genestrt.STRING_OFS_LIST)}")
            if any(genestrt.STRING_OFS_LIST_PAD):
                violations.append(f"All bytes of {name}.STRING_OFS_LIST_PAD must be 0")
            if len(genestrt.STRING_LIST) != genestrt.STRING_COUNT:
                violations.append(f"Length of {name}.STRING_LIST must be {genestrt.STRING_COUNT}, current: {len(genestrt.STRING_LIST)}")
            if any(genestrt.STRING_LIST_PAD):
                violations.append(f"All bytes of {name}.STRING_LIST_PAD must be 0")
        return violations

    def _validate_geneeof(self, geneeof: GENEEOF, name: str) -> list[str]:
        violations: list[str] = []
        if geneeof.SIGNATURE != b"GENEEOF ":
            violations.append(f"{name}.SIGNATURE must be 'GENEEOF ', current: '{self._sig(geneeof.SIGNATURE)}'")
        else:
            if geneeof.TABLE_SIZE != 0:
                violations.append(f"Size of {name} table must be 0, current: {geneeof.TABLE_SIZE}")
        return violations

    def _validate_file_sets(self) -> list[str]:
        violations: list[str] = []
        if len(self._FILE_SETS) != self._PACKFSLS.FS_SEG_COUNT:
            violations.append(f"Count of FILE_SET must be {self._PACKFSLS.FS_SEG_COUNT}, current: {len(self._FILE_SETS)}")

        # FS is padded to FS_PAD_TYPE, but the first FS always starts at a multiple of 2048
        fs_align = {1: 2048, 2: 512}.get(self._PACKHEDR.FS_PAD_TYPE)
        first_fs_ofs = min((fs.SEGMENT.FS_ABSOLUTE_OFS for fs in self._FILE_SETS), default=0)

        for i, fs in enumerate(self._FILE_SETS):
            name = f"FILE_SET[{i}]"
            align = 2048 if fs.SEGMENT.FS_ABSOLUTE_OFS == first_fs_ofs else fs_align
            if align and fs.SEGMENT.FS_ABSOLUTE_OFS % align != 0:
                violations.append(f"Offset of {name} must be a multiple of {align}, current: {fs.SEGMENT.FS_ABSOLUTE_OFS}")

            violations += self._validate_endiltle(fs.FS_ENDILTLE, f"{name}.FS_ENDILTLE")
            violations += self._validate_packfshd(fs, name)
            violations += self._validate_genestrt(fs.FS_GENESTRT, f"{name}.FS_GENESTRT")
            violations += self._validate_geneeof(fs.FS_GENEEOF, f"{name}.FS_GENEEOF")
        return violations

    def _validate_packfshd(self, fs: FILE_SET, name: str) -> list[str]:
        violations: list[str] = []
        packfshd = fs.FS_PACKFSHD
        if packfshd.SIGNATURE != b"PACKFSHD":
            violations.append(f"{name}.FS_PACKFSHD.SIGNATURE must be 'PACKFSHD', current: '{self._sig(packfshd.SIGNATURE)}'")
            return violations

        expected_table_size = self._align16_size(4 * 8 + (packfshd.FILE_SEG_SIZE * packfshd.FILE_SEG_COUNT))
        if packfshd.TABLE_SIZE != expected_table_size:
            violations.append(f"Size of {name}.FS_PACKFSHD table must be {expected_table_size}, current: {packfshd.TABLE_SIZE}")
        if packfshd.unknown_1 != 65536:
            violations.append(f"Value of {name}.FS_PACKFSHD.unknown_1 must be 65536, current: {packfshd.unknown_1}")
        if packfshd.FILE_SEG_SIZE != 32:
            violations.append(f"Size of {name}.FS_PACKFSHD.FILE_SEG_SIZE must be 32, current: {packfshd.FILE_SEG_SIZE}")
        if packfshd.FS_FILE_SEG_LIST_OFS != 32:
            violations.append(f"Offset of {name}.FS_PACKFSHD.FS_FILE_SEG_LIST_OFS must be 32, current: {packfshd.FS_FILE_SEG_LIST_OFS}")
        # size of ENDILTLE + PACKFSHD + GENESTRT (the engine does not use this field)
        geneeof_ofs = 16 + (16 + packfshd.TABLE_SIZE) + (16 + fs.FS_GENESTRT.TABLE_SIZE)
        if packfshd.GENEEOF_OFS != geneeof_ofs:
            log.warning("Value of %s.FS_PACKFSHD.GENEEOF_OFS may be %d, current: %d", name, geneeof_ofs, packfshd.GENEEOF_OFS)
        for field in ("unknown_2", "unknown_3", "unknown_4"):
            if getattr(packfshd, field) != 0:
                log.warning("Value of %s.FS_PACKFSHD.%s may be 0, current: %d", name, field, getattr(packfshd, field))
        if len(packfshd.FS_FILE_SEG_LIST) != packfshd.FILE_SEG_COUNT:
            violations.append(f"Length of {name}.FS_PACKFSHD.FS_FILE_SEG_LIST must be {packfshd.FILE_SEG_COUNT}, current: {len(packfshd.FS_FILE_SEG_LIST)}")

        # the first file starts right after GENEEOF
        string_count = len(fs.FS_GENESTRT.STRING_LIST)
        files_ofs = geneeof_ofs + 16
        first_file_ofs = min((seg.FILE_OFS for seg in packfshd.FS_FILE_SEG_LIST), default=files_ofs)
        if first_file_ofs != files_ofs:
            violations.append(f"The first FILE_OFS of {name} must be {files_ofs}, current: {first_file_ofs}")

        for i, seg in enumerate(packfshd.FS_FILE_SEG_LIST):
            if seg.NAME_IDX >= string_count:
                violations.append(f"{name}.FS_FILE_SEG_LIST[{i}].NAME_IDX must be less than {string_count}, current: {seg.NAME_IDX}")
            if seg.COMPRESS_TYPE not in [0, 2]:
                violations.append(f"{name}.FS_FILE_SEG_LIST[{i}].COMPRESS_TYPE must be 0 or 2, current: {seg.COMPRESS_TYPE}")
            for field in ("unknown_1", "unknown_2", "unknown_3"):
                if getattr(seg, field) != 0:
                    log.warning("Value of %s.FS_FILE_SEG_LIST[%d].%s may be 0, current: %d", name, i, field, getattr(seg, field))
            if seg.FILE_SIZE <= 0:
                violations.append(f"{name}.FS_FILE_SEG_LIST[{i}].FILE_SIZE must be greater than 0, current: {seg.FILE_SIZE}")
            if seg.COMPRESS_TYPE == 2 and seg.FILE_ZSIZE <= 0:
                violations.append(f"{name}.FS_FILE_SEG_LIST[{i}].FILE_ZSIZE must be greater than 0 for a compressed file, current: {seg.FILE_ZSIZE}")
            if seg.COMPRESS_TYPE == 0 and seg.FILE_ZSIZE != 0:
                violations.append(f"{name}.FS_FILE_SEG_LIST[{i}].FILE_ZSIZE must be 0 for an uncompressed file, current: {seg.FILE_ZSIZE}")
        return violations

    def _validate_toc_segments(self) -> list[str]:
        violations: list[str] = []
        segs = self._PACKTOC.TOC_SEG_LIST
        string_count = len(self._GENESTRT.STRING_LIST)

        for i, seg in enumerate(segs):
            if seg.IDENTIFIER not in [0, 1]:
                violations.append(f"TOC_SEG_LIST[{i}].IDENTIFIER must be 0 or 1, current: {seg.IDENTIFIER}")
                continue
            if seg.COMPRESS_TYPE not in [0, 2]:
                violations.append(f"TOC_SEG_LIST[{i}].COMPRESS_TYPE must be 0 or 2, current: {seg.COMPRESS_TYPE}")
            if seg.unknown_1 != 0:
                log.warning("Value of TOC_SEG_LIST[%d].unknown_1 may be 0, current: %s", i, seg.unknown_1)
            if seg.NAME_IDX >= string_count:
                violations.append(f"TOC_SEG_LIST[{i}].NAME_IDX must be less than {string_count}, current: {seg.NAME_IDX}")
            if seg.PACKAGE_NAME_IDX != 0:
                log.warning("Value of TOC_SEG_LIST[%d].PACKAGE_NAME_IDX may be 0, current: %s", i, seg.PACKAGE_NAME_IDX)
            if seg.unknown_2 != 0:
                log.warning("Value of TOC_SEG_LIST[%d].unknown_2 may be 0, current: %s", i, seg.unknown_2)

            if seg.IDENTIFIER == 1:  # Directory
                if seg.COMPRESS_TYPE != 0:
                    violations.append(f"TOC_SEG_LIST[{i}].COMPRESS_TYPE must be 0 for a directory, current: {seg.COMPRESS_TYPE}")
                if seg.ENTRY_INDEX + seg.ENTRY_COUNT > len(segs):
                    violations.append(f"Children of TOC_SEG_LIST[{i}] are out of range: [{seg.ENTRY_INDEX}, {seg.ENTRY_INDEX + seg.ENTRY_COUNT}) of {len(segs)}")
                if seg.unused_1 != 0:
                    log.warning("Value of TOC_SEG_LIST[%d].unused_1 may be 0, current: %s", i, seg.unused_1)
                if seg.unused_2 != 0:
                    log.warning("Value of TOC_SEG_LIST[%d].unused_2 may be 0, current: %s", i, seg.unused_2)
            else:  # File
                if seg.FILE_SIZE <= 0:
                    violations.append(f"TOC_SEG_LIST[{i}].FILE_SIZE must be greater than 0, current: {seg.FILE_SIZE}")
                if seg.COMPRESS_TYPE == 2 and seg.FILE_ZSIZE <= 0:
                    violations.append(f"TOC_SEG_LIST[{i}].FILE_ZSIZE must be greater than 0 for a compressed file, current: {seg.FILE_ZSIZE}")
                if seg.COMPRESS_TYPE == 0 and seg.FILE_ZSIZE != 0:
                    violations.append(f"TOC_SEG_LIST[{i}].FILE_ZSIZE must be 0 for an uncompressed file, current: {seg.FILE_ZSIZE}")
        return violations

    def _validate_fs_segments(self) -> list[str]:
        violations: list[str] = []
        string_count = len(self._GENESTRT.STRING_LIST)

        for i, seg in enumerate(self._PACKFSLS.FS_SEG_LIST):
            if seg.NAME_IDX >= string_count:
                violations.append(f"FS_SEG_LIST[{i}].NAME_IDX must be less than {string_count}, current: {seg.NAME_IDX}")
            if seg.PACKAGE_NAME_IDX != 0:
                log.warning("Value of FS_SEG_LIST[%d].PACKAGE_NAME_IDX may be 0, current: %s", i, seg.PACKAGE_NAME_IDX)
            # TODO FS_HASH is not checked here since it requires reading the data of the FS
        return violations

    def _validate_toc_order(self) -> list[str]:
        violations: list[str] = []
        segs = self._PACKTOC.TOC_SEG_LIST
        strings = self._GENESTRT.STRING_LIST

        for i, seg in enumerate(segs):
            if seg.IDENTIFIER != 1 or seg.ENTRY_COUNT < 2:  # only directories with 2+ children
                continue
            children = segs[seg.ENTRY_INDEX: seg.ENTRY_INDEX + seg.ENTRY_COUNT]
            if any(c.NAME_IDX >= len(strings) for c in children):  # reported by _validate_toc_segments()
                continue
            names = [strings[c.NAME_IDX].encode("utf-8") for c in children]
            if any(a >= b for a, b in zip(names, names[1:])):
                violations.append(f"Children of TOC_SEG_LIST[{i}] are not sorted by name")
        return violations


class ApkException(Exception):
    def __init__(self, violations: list[str]) -> None:
        super().__init__(f"APK validation failed: {len(violations)} violation(s)")
        self.violations = violations
