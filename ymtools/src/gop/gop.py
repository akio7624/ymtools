import logging
from pathlib import Path

from ymtools.src.apkidx.structure._reader import read_geneeof
from ymtools.src.apkidx.structure._tables import GENEEOF, GENESTRT
from ymtools.src.apkidx.structure._validator import raise_if_invalid, validate_geneeof
from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.gop._reader import read_gdat, read_genestrt, read_gfin, read_gmet, read_grec
from ymtools.src.gop._tables import GOP_GDAT, GOP_GFIN, GOP_GMET, GOP_GREC
from ymtools.src.gop._validator import validate_gdat, validate_genestrt, validate_gfin, validate_gmet, validate_grec
from ymtools.src.gop.exceptions import GopException

__all__ = ["GOP", "GopException"]
log = logging.getLogger(__name__)


class GOP:
    def __init__(
        self,
        gfin: GOP_GFIN,
        gmet: GOP_GMET,
        grec: GOP_GREC,
        genestrt: GENESTRT,
        gdat: GOP_GDAT,
        geneeof: GENEEOF,
    ) -> None:
        self._GFIN = gfin
        self._GMET = gmet
        self._GREC = grec
        self._GENESTRT = genestrt
        self._GDAT = gdat
        self._GENEEOF = geneeof

    @classmethod
    def read_gop(cls, path: Path) -> "GOP":
        log.info(f"reading GOP: {path}")

        with BinaryReader(path) as br:
            # ====================== ENDIBIGE ======================
            signature = br.read_bytes(8)
            br.skip(-8)
            if signature == b"ENDIBIGE":
                raise GopException(["Big endian gop file is not supported"])

            # ====================== GOP GFIN ======================
            log.info(f"Processing table GOP GFIN")
            gfin = read_gfin(br)

            # ====================== GOP GMET ======================
            log.info(f"Processing table GOP GMET")
            gmet = read_gmet(br)

            # ====================== GOP GREC ======================
            log.info(f"Processing table GOP GREC")
            grec = read_grec(br)

            # ====================== GENESTRT ======================
            log.info(f"Processing table GENESTRT")
            genestrt = read_genestrt(br)

            # ====================== GOP GDAT ======================
            log.info(f"Processing table GOP GDAT")
            gdat = read_gdat(br)

            # ====================== GENEEOF ======================
            log.info(f"Processing table GENEEOF")
            geneeof = read_geneeof(br)

        gop = cls(
            gfin=gfin,
            gmet=gmet,
            grec=grec,
            genestrt=genestrt,
            gdat=gdat,
            geneeof=geneeof,
        )

        violations = gop.validate()
        raise_if_invalid(violations, GopException)

        return gop

    def validate(self) -> list[str]:
        violations: list[str] = []

        # check for GFIN
        violations += validate_gfin(self._GFIN)

        # check for GENESTRT
        genestrt_violations = validate_genestrt(self._GENESTRT, "GENESTRT")
        violations += genestrt_violations

        # the other tables refer to the strings, so they are checked only if GENESTRT is valid
        if not genestrt_violations:
            # check for GMET
            violations += validate_gmet(self._GMET, self._GENESTRT)

            # check for GREC
            violations += validate_grec(self._GREC, self._GENESTRT)

            # check for GDAT
            if self._GREC.SIGNATURE == b"GOP GREC":
                violations += validate_gdat(self._GDAT, self._GREC, self._GENESTRT)

        # check for GENEEOF
        violations += validate_geneeof(self._GENEEOF, "GENEEOF")

        return violations

    # ========= utils ==========
    def get_gfin(self) -> GOP_GFIN:
        return self._GFIN

    def get_gmet(self) -> GOP_GMET:
        return self._GMET

    def get_grec(self) -> GOP_GREC:
        return self._GREC

    def get_gdat(self) -> GOP_GDAT:
        return self._GDAT

    def get_string_list(self) -> list[str]:
        return self._GENESTRT.STRING_LIST
