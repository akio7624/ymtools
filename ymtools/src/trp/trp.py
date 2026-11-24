import hashlib
import logging
from pathlib import Path

from ymtools.src.apkidx.structure._validator import raise_if_invalid
from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.trp._reader import read_entry_list, read_header
from ymtools.src.trp._tables import TRP_FILE_ENTRY, TRP_HEADER
from ymtools.src.trp._validator import validate_entry_list, validate_header
from ymtools.src.trp.exceptions import TrpException

__all__ = ["TRP", "TrpException"]
log = logging.getLogger(__name__)


class TRP:
    def __init__(self, header: TRP_HEADER, entry_list: list[TRP_FILE_ENTRY]) -> None:
        self._HEADER = header
        self._ENTRY_LIST = entry_list

    @classmethod
    def read_trp(cls, path: Path) -> "TRP":
        log.info(f"reading TRP: {path}")

        with BinaryReader(path) as br:
            # ====================== HEADER ======================
            log.info(f"Processing HEADER")
            header = read_header(br)

            # ====================== ENTRY LIST ======================
            log.info(f"Processing ENTRY_LIST")
            entry_list = read_entry_list(br, header.FILE_COUNT)

            # pre-calculate sha1, the HASH field is treated as 0 while calculating
            actual_file_size = path.stat().st_size
            br.seek(0)
            sha1 = hashlib.sha1()
            sha1.update(br.read_bytes(28))
            br.skip(20)
            sha1.update(bytes(20))
            for chunk in br.read_chunks(actual_file_size - 48):
                sha1.update(chunk)
            header.actual_file_size = actual_file_size
            header.actual_hash = sha1.digest()

        trp = cls(header=header, entry_list=entry_list)

        violations = trp.validate()
        raise_if_invalid(violations, TrpException)

        return trp

    def validate(self) -> list[str]:
        violations: list[str] = []

        # check for HEADER
        header_violations = validate_header(self._HEADER, self._ENTRY_LIST)
        violations += header_violations

        # the layout of the files is checked only if HEADER is valid
        if not header_violations:
            # check for ENTRY_LIST
            violations += validate_entry_list(self._HEADER, self._ENTRY_LIST)

        return violations

    # ========= utils ==========
    def get_header(self) -> TRP_HEADER:
        return self._HEADER

    def get_entry_list(self) -> list[TRP_FILE_ENTRY]:
        return self._ENTRY_LIST
