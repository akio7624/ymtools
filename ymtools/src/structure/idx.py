import logging
from pathlib import Path

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.structure._reader import read_endiltle, read_geneeof, read_genestrt, read_packfsls, read_packhedr, read_packtoc
from ymtools.src.structure._tables import ENDILTLE, GENEEOF, GENESTRT, PACKFSLS, PACKHEDR, PACKTOC
from ymtools.src.structure._validator import raise_if_invalid, validate_endiltle, validate_geneeof, validate_genestrt, validate_packfsls, validate_packhedr, validate_packtoc, validate_toc_order
from ymtools.src.structure.exceptions import IdxException

__all__ = ["IDX", "IdxException"]
log = logging.getLogger(__name__)


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

        # check for PACKTOC
        violations += validate_packtoc(self._PACKTOC)
        if self._PACKTOC.SIGNATURE == b"PACKTOC ":
            violations += validate_toc_order(self._PACKTOC, self._GENESTRT)

        # check for PACKFSLS
        violations += validate_packfsls(self._PACKFSLS)

        # check for GENESTRT
        violations += validate_genestrt(self._GENESTRT, "GENESTRT")

        # check for GENEEOF
        violations += validate_geneeof(self._GENEEOF, "GENEEOF")

        return violations
