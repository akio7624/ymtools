import logging
from pathlib import Path

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.structure._reader import read_endiltle, read_geneeof, read_genestrt, read_packfsls, read_packhedr, read_packtoc
from ymtools.src.structure._tables import ENDILTLE, FS_SEGMENT, GENEEOF, GENESTRT, PACKFSLS, PACKHEDR, PACKTOC
from ymtools.src.structure._validator import raise_if_invalid, validate_endiltle, validate_geneeof, validate_genestrt, validate_fs_segments, validate_packfsls, validate_packhedr, validate_packtoc, validate_toc_order, validate_toc_segments
from ymtools.src.structure.apk import APK
from ymtools.src.structure.exceptions import IdxException
from ymtools.src.structure.utils import resolve_apk_path, walk_toc

__all__ = ["IDX", "IdxException"]
log = logging.getLogger(__name__)


def _fmt(value: object) -> str:
    return value.hex() if isinstance(value, bytes) else str(value)


class IDX:
    def __init__(
        self,
        endiltle: ENDILTLE,
        packhedrs: list[PACKHEDR],
        packtoc: PACKTOC,
        packfsls: PACKFSLS,
        genestrt: GENESTRT,
        geneeof: GENEEOF,
    ) -> None:
        self._ENDILTLE = endiltle
        self._PACKHEDRS = packhedrs
        self._PACKTOC = packtoc
        self._PACKFSLS = packfsls
        self._GENESTRT = genestrt
        self._GENEEOF = geneeof

    @classmethod
    def read_idx(cls, path: Path) -> "IDX":
        log.info(f"reading IDX: {path}")

        with BinaryReader(path) as br:
            # ====================== ENDILTLE ======================
            log.info(f"Processing table ENDILTLE")
            endiltle = read_endiltle(br)

            # ====================== PACKHEDR ======================
            log.info(f"Processing table PACKHEDR")
            packhedrs: list[PACKHEDR] = []
            # PACKHEDR exists as many as the number of apk files, so read until the next table appears
            while True:
                signature = br.read_bytes(8)
                br.skip(-8)
                if signature != b"PACKHEDR":
                    break

                packhedrs.append(read_packhedr(br))

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

        idx = cls(
            endiltle=endiltle,
            packhedrs=packhedrs,
            packtoc=packtoc,
            packfsls=packfsls,
            genestrt=genestrt,
            geneeof=geneeof,
        )

        violations = idx.validate()
        raise_if_invalid(violations, IdxException)

        return idx

    def validate(self) -> list[str]:
        violations: list[str] = []

        # check for ENDILTLE
        violations += validate_endiltle(self._ENDILTLE, "ENDILTLE")

        # check for PACKHEDR
        if len(self._PACKHEDRS) == 0:
            violations.append("At least one PACKHEDR table is required")
        for i, packhedr in enumerate(self._PACKHEDRS):
            violations += validate_packhedr(packhedr, f"PACKHEDR[{i}]", i)
            if packhedr.NAME_IDX >= len(self._GENESTRT.STRING_LIST):
                violations.append(f"PACKHEDR[{i}].NAME_IDX must be less than {len(self._GENESTRT.STRING_LIST)}, current: {packhedr.NAME_IDX}")

        # check for PACKTOC
        violations += validate_packtoc(self._PACKTOC)
        if self._PACKTOC.SIGNATURE == b"PACKTOC ":
            violations += validate_toc_segments(self._PACKTOC, self._GENESTRT, False)
            violations += validate_toc_order(self._PACKTOC, self._GENESTRT)

        # check for PACKFSLS
        violations += validate_packfsls(self._PACKFSLS)
        if self._PACKFSLS.SIGNATURE == b"PACKFSLS":
            violations += validate_fs_segments(self._PACKFSLS, self._GENESTRT, False)

        # check for GENESTRT
        violations += validate_genestrt(self._GENESTRT, "GENESTRT")

        # check for GENEEOF
        violations += validate_geneeof(self._GENEEOF, "GENEEOF")

        return violations

    def validate_detail(self, idx_dir: Path, base: Path | None) -> list[str]:
        violations: list[str] = []
        strings = self._GENESTRT.STRING_LIST
        recorded_paths = [strings[packhedr.NAME_IDX] for packhedr in self._PACKHEDRS]

        # ====================== locate and read apk files ======================
        apks: list[APK] = []
        apk_sizes: list[int] = []
        for i, recorded in enumerate(recorded_paths):
            try:
                apk_path = resolve_apk_path(idx_dir, base, recorded)
            except ValueError as e:
                return [f"PACKHEDR[{i}]: {e}"]
            if not apk_path.is_file():
                return [f"PACKHEDR[{i}]: apk file not found: {apk_path} (recorded path: '{recorded}')"]

            log.info(f"Reading apk of PACKHEDR[{i}]: {apk_path}")
            apks.append(APK.read_apk(apk_path))
            apk_sizes.append(apk_path.stat().st_size)

        if len(set(recorded_paths)) != len(recorded_paths):
            violations.append("The paths of PACKHEDR must not be duplicated")

        violations += self._validate_detail_packhedr(apks, recorded_paths)
        violations += self._validate_detail_toc(apks, apk_sizes, recorded_paths)
        violations += self._validate_detail_fs(apks, apk_sizes, recorded_paths)
        self._validate_detail_genestrt(apks, recorded_paths)  # only warns
        return violations

    def _validate_detail_packhedr(self, apks: list[APK], recorded_paths: list[str]) -> list[str]:
        violations: list[str] = []
        for i, (packhedr, apk) in enumerate(zip(self._PACKHEDRS, apks)):
            apk_packhedr = apk.get_packhedr()
            # NAME_IDX is rewritten to match the GENESTRT of the idx, other fields are copied
            for field in ("unknown_1", "ROOT_FILES_OFS", "FS_PAD_TYPE", "HASH"):
                if getattr(packhedr, field) != getattr(apk_packhedr, field):
                    violations.append(f"PACKHEDR[{i}].{field} must be the same as the apk '{recorded_paths[i]}', current: {_fmt(getattr(packhedr, field))}, apk: {_fmt(getattr(apk_packhedr, field))}")
        return violations

    def _validate_detail_toc(self, apks: list[APK], apk_sizes: list[int], recorded_paths: list[str]) -> list[str]:
        violations: list[str] = []
        segs = self._PACKTOC.TOC_SEG_LIST
        paths, _ = walk_toc(segs, self._GENESTRT.STRING_LIST)

        # path -> index of the segment in the idx
        idx_seg_of: dict[str, int] = {}
        for j, path in enumerate(paths):
            if path is None:
                violations.append(f"TOC_SEG_LIST[{j}] is not reachable from the root")
            elif j != 0:
                idx_seg_of[path] = j
                if segs[j].IDENTIFIER == 1 and segs[j].PACKAGE_NAME_IDX != 0:
                    violations.append(f"TOC_SEG_LIST[{j}].PACKAGE_NAME_IDX must be 0 for a directory, current: {segs[j].PACKAGE_NAME_IDX}")

        file_owner: dict[str, int] = {}  # path of file -> index of the apk
        dirs_in_apks: set[str] = set()
        for i, apk in enumerate(apks):
            apk_segs = apk.get_toc_seg_list()
            apk_paths, _ = walk_toc(apk_segs, apk.get_string_list())
            for j, path in enumerate(apk_paths):
                if j == 0 or path is None:
                    continue
                apk_seg = apk_segs[j]
                idx_j = idx_seg_of.get(path)
                if idx_j is None:
                    violations.append(f"'{path}' of the apk '{recorded_paths[i]}' is missing in the idx")
                    continue
                idx_seg = segs[idx_j]
                if idx_seg.IDENTIFIER != apk_seg.IDENTIFIER:
                    violations.append(f"TOC_SEG_LIST[{idx_j}] '{path}' has a different IDENTIFIER from the apk '{recorded_paths[i]}', current: {idx_seg.IDENTIFIER}, apk: {apk_seg.IDENTIFIER}")
                    continue

                if apk_seg.IDENTIFIER == 1:  # Directory, the same directory of apks is merged into one
                    dirs_in_apks.add(path)
                    continue

                # File
                if path in file_owner:
                    violations.append(f"'{path}' exists in both the apk '{recorded_paths[file_owner[path]]}' and '{recorded_paths[i]}'")
                    continue
                file_owner[path] = i
                if idx_seg.PACKAGE_NAME_IDX != self._PACKHEDRS[i].NAME_IDX:
                    violations.append(f"TOC_SEG_LIST[{idx_j}].PACKAGE_NAME_IDX of '{path}' must be {self._PACKHEDRS[i].NAME_IDX} (the apk '{recorded_paths[i]}'), current: {idx_seg.PACKAGE_NAME_IDX}")
                for field in ("COMPRESS_TYPE", "FILE_ABSOLUTE_OFS", "FILE_SIZE", "FILE_ZSIZE"):
                    if getattr(idx_seg, field) != getattr(apk_seg, field):
                        violations.append(f"TOC_SEG_LIST[{idx_j}].{field} of '{path}' must be the same as the apk '{recorded_paths[i]}', current: {getattr(idx_seg, field)}, apk: {getattr(apk_seg, field)}")
                stored_size = idx_seg.FILE_ZSIZE if idx_seg.COMPRESS_TYPE == 2 else idx_seg.FILE_SIZE
                if idx_seg.FILE_ABSOLUTE_OFS + stored_size > apk_sizes[i]:
                    violations.append(f"The data of '{path}' is out of the range of the apk '{recorded_paths[i]}': [{idx_seg.FILE_ABSOLUTE_OFS}, {idx_seg.FILE_ABSOLUTE_OFS + stored_size}) of {apk_sizes[i]}")

        # the idx must not have anything that does not exist in the apks
        for path, idx_j in idx_seg_of.items():
            if segs[idx_j].IDENTIFIER == 0 and path not in file_owner:
                violations.append(f"TOC_SEG_LIST[{idx_j}] '{path}' does not exist in any apk")
            elif segs[idx_j].IDENTIFIER == 1 and path not in dirs_in_apks:
                violations.append(f"TOC_SEG_LIST[{idx_j}] '{path}' (directory) does not exist in any apk")
        return violations

    def _validate_detail_fs(self, apks: list[APK], apk_sizes: list[int], recorded_paths: list[str]) -> list[str]:
        violations: list[str] = []
        strings = self._GENESTRT.STRING_LIST

        # name of FS -> segment in the idx
        idx_seg_of: dict[str, FS_SEGMENT] = {}
        for j, seg in enumerate(self._PACKFSLS.FS_SEG_LIST):
            name = strings[seg.NAME_IDX]
            if name in idx_seg_of:
                violations.append(f"FS_SEG_LIST[{j}] '{name}' is duplicated")
            idx_seg_of[name] = seg

        fs_owner: dict[str, int] = {}  # name of FS -> index of the apk
        for i, apk in enumerate(apks):
            apk_strings = apk.get_string_list()
            for fs in apk.get_file_sets():
                apk_seg = fs.SEGMENT
                name = apk_strings[apk_seg.NAME_IDX]
                idx_seg = idx_seg_of.get(name)
                if idx_seg is None:
                    violations.append(f"The FS '{name}' of the apk '{recorded_paths[i]}' is missing in the idx")
                    continue
                if name in fs_owner:
                    violations.append(f"The FS '{name}' exists in both the apk '{recorded_paths[fs_owner[name]]}' and '{recorded_paths[i]}'")
                    continue
                fs_owner[name] = i
                if idx_seg.PACKAGE_NAME_IDX != self._PACKHEDRS[i].NAME_IDX:
                    violations.append(f"The PACKAGE_NAME_IDX of the FS '{name}' must be {self._PACKHEDRS[i].NAME_IDX} (the apk '{recorded_paths[i]}'), current: {idx_seg.PACKAGE_NAME_IDX}")
                for field in ("FS_ABSOLUTE_OFS", "FS_SIZE", "FS_HASH"):
                    if getattr(idx_seg, field) != getattr(apk_seg, field):
                        violations.append(f"The {field} of the FS '{name}' must be the same as the apk '{recorded_paths[i]}', current: {_fmt(getattr(idx_seg, field))}, apk: {_fmt(getattr(apk_seg, field))}")
                if idx_seg.FS_ABSOLUTE_OFS + idx_seg.FS_SIZE > apk_sizes[i]:
                    violations.append(f"The FS '{name}' is out of the range of the apk '{recorded_paths[i]}': [{idx_seg.FS_ABSOLUTE_OFS}, {idx_seg.FS_ABSOLUTE_OFS + idx_seg.FS_SIZE}) of {apk_sizes[i]}")

        for name in idx_seg_of:
            if name not in fs_owner:
                violations.append(f"The FS '{name}' does not exist in any apk")
        return violations

    def _validate_detail_genestrt(self, apks: list[APK], recorded_paths: list[str]) -> None:
        # the engine accesses strings by index, so a different order is not a violation. warn only once, not for each string
        actual = self._GENESTRT.STRING_LIST

        # expected order: paths of apks -> empty string for the root -> names of TOC -> names of FS (without duplicates)
        expected: list[str] = []
        seen: set[str] = set()

        def add(string: str) -> None:
            if string not in seen:
                seen.add(string)
                expected.append(string)

        for recorded in recorded_paths:
            add(recorded)
        add("")
        _, order = walk_toc(self._PACKTOC.TOC_SEG_LIST, actual)
        for j in order:
            add(actual[self._PACKTOC.TOC_SEG_LIST[j].NAME_IDX])
        for apk in apks:
            for fs in apk.get_file_sets():
                add(apk.get_string_list()[fs.SEGMENT.NAME_IDX])

        if actual == expected:
            return
        if sorted(actual) == sorted(expected):
            first = next(k for k, (a, e) in enumerate(zip(actual, expected)) if a != e)
            log.warning("The order of GENESTRT.STRING_LIST differs from the expected one, first difference at index %d: current '%s', expected '%s'", first, actual[first], expected[first])
        else:
            missing = [e for e in expected if e not in set(actual)]
            extra = [a for a in actual if a not in seen]
            log.warning("The strings of GENESTRT.STRING_LIST differ from the expected ones, missing: %d (ex: %s), extra: %d (ex: %s)", len(missing), missing[:3], len(extra), extra[:3])
