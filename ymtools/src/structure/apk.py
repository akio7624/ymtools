import struct
from pathlib import Path

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.structure._tables import ENDILTLE, FILE_SET, GENEEOF, GENESTRT, PACKFSLS, PACKHEDR, PACKTOC


__all__ = ["APK"]


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
        with BinaryReader(path) as br:
            endiltle = ENDILTLE(
                SIGNATURE=br.read_struct(struct.Struct("<8s"))[0],
                TABLE_SIZE=br.read_struct(struct.Struct("<Q"))[0]
            )

        apk = cls(
            endiltle=endiltle,
            # TODO ...
        )
        violations = apk.validate()
        if violations:
            # TODO 예외처리 등
            pass
        return apk

    def validate(self) -> list[str]:
        violations: list[str] = []

        if self._ENDILTLE.SIGNATURE != b"ENDILTLE":
            violations.append("some error...")
