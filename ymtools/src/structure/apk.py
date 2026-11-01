import hashlib
import logging
import struct
from pathlib import Path

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.structure._reader import read_endiltle, read_geneeof, read_genestrt, read_packfsls, read_packhedr, read_packtoc
from ymtools.src.structure._tables import ENDILTLE, FILE_SET, GENEEOF, GENESTRT, PACKFSHD, PACKFSLS, PACKHEDR, PACKTOC, FS_FILE_SEG
from ymtools.src.structure._validator import raise_if_invalid, validate_endiltle, validate_geneeof, validate_genestrt, validate_packfsls, validate_packhedr, validate_packtoc, validate_toc_order
from ymtools.src.structure.exceptions import ApkException
from ymtools.src.structure.utils import get_align16_count, get_align16_size, sig_to_str

__all__ = ["APK", "ApkException"]
log = logging.getLogger(__name__)


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
            endiltle = read_endiltle(br)

            # ====================== PACKHEDR ======================
            log.info(f"Processing table PACKHEDR")
            packhedr = read_packhedr(br)

            # ====================== PACKTOC ======================
            log.info(f"Processing table PACKTOC")
            packtoc = read_packtoc(br)

            # ====================== PACKFSLS ======================
            log.info(f"Processing table PACKFSLS")
            packfsls = read_packfsls(br)

            # ====================== GENESTRT ======================
            log.info(f"Processing table GENESTRT")
            genestrt = read_genestrt(br)

            # ====================== GENEEOF ======================
            log.info(f"Processing table GENEEOF")
            geneeof = read_geneeof(br)

            # ====================== File Set List ======================
            file_sets: list[FILE_SET] = []
            for i, fs_seg in enumerate(packfsls.FS_SEG_LIST):
                log.info(f"Processing FILE_SET[{i}]")

                # pre-calculate md5
                br.seek(fs_seg.FS_ABSOLUTE_OFS)
                md5 = hashlib.md5()
                for chunk in br.read_chunks(fs_seg.FS_SIZE):
                    md5.update(chunk)
                fs_seg.actual_hash = md5.digest()

                br.seek(fs_seg.FS_ABSOLUTE_OFS)

                # ---------------------- ENDILTLE ----------------------
                fs_endiltle = read_endiltle(br)

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
                fs_genestrt = read_genestrt(br)

                # ---------------------- GENEEOF ----------------------
                fs_geneeof = read_geneeof(br)

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
        raise_if_invalid(violations, ApkException)

        return apk

    def validate(self) -> list[str]:
        violations: list[str] = []

        # check for ENDILTLE
        violations += validate_endiltle(self._ENDILTLE, "ENDILTLE")

        # check for PACKHEDR
        violations += validate_packhedr(self._PACKHEDR, "PACKHEDR", 0)

        # check for PACKTOC
        violations += validate_packtoc(self._PACKTOC)
        if self._PACKTOC.SIGNATURE == b"PACKTOC ":  # segments are checked only if the table itself is valid
            violations += self._validate_toc_segments()
            violations += validate_toc_order(self._PACKTOC, self._GENESTRT)

        # check for PACKFSLS
        violations += validate_packfsls(self._PACKFSLS)
        if self._PACKFSLS.SIGNATURE == b"PACKFSLS":
            violations += self._validate_fs_segments()

        # check for GENESTRT
        violations += validate_genestrt(self._GENESTRT, "GENESTRT")

        # check for GENEEOF
        violations += validate_geneeof(self._GENEEOF, "GENEEOF")

        # check for File Sets
        violations += self._validate_file_sets()

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

            violations += validate_endiltle(fs.FS_ENDILTLE, f"{name}.FS_ENDILTLE")
            violations += self._validate_packfshd(fs, name)
            violations += validate_genestrt(fs.FS_GENESTRT, f"{name}.FS_GENESTRT")
            violations += validate_geneeof(fs.FS_GENEEOF, f"{name}.FS_GENEEOF")
        return violations

    def _validate_packfshd(self, fs: FILE_SET, name: str) -> list[str]:
        violations: list[str] = []
        packfshd = fs.FS_PACKFSHD
        if packfshd.SIGNATURE != b"PACKFSHD":
            violations.append(f"{name}.FS_PACKFSHD.SIGNATURE must be 'PACKFSHD', current: '{sig_to_str(packfshd.SIGNATURE)}'")
            return violations

        expected_table_size = get_align16_size(4 * 8 + (packfshd.FILE_SEG_SIZE * packfshd.FILE_SEG_COUNT))
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
            actual_hash = seg.actual_hash  # property access is not narrowed by the type checker, so keep it in a local
            if actual_hash is not None and actual_hash != seg.FS_HASH:
                violations.append(f"FS_SEG_LIST[{i}].FS_HASH must be {actual_hash.hex()}, current: {seg.FS_HASH.hex()}")
        return violations
