import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ymtools.src import const
from ymtools.src.apkidx.structure.utils import get_align16_size
from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.binutils.BinaryWriter import BinaryWriter
from ymtools.src.trp._tables import TRP_FILE_ENTRY, TRP_HEADER
from ymtools.src.trp._writer import make_entry_list, make_header
from ymtools.src.trp.exceptions import TrpPackException

log = logging.getLogger(__name__)


"""
패킹 과정 정리
1. 메타데이터 파일을 읽는다(필수)
2. 입력 디렉터리의 파일을 수집한다. 메타데이터에 있는 파일은 그 순서대로 앞에, 없는 파일은 경고 후 이름순으로 뒤에 둔다
3. 파일 크기로 각 엔트리의 START_OFS와 전체 크기 FILE_SIZE를 계산하여 헤더와 엔트리 목록 객체를 만든다
4. 임시 파일에 헤더와 엔트리 목록 크기만큼 앞에 빈 공간 만들고, 파일을 순서대로 쓰며 각 파일에 대한 패딩을 적용한다
5. 헤더와 엔트리 목록을 예약된 공간에 기록하고 flush한다
6. 헤더의 HASH 필드를 0으로 보고 임시 파일 전체의 SHA1을 계산하여 HASH를 기록한다
7. 임시파일을 출력 파일로 이름 바꾼다(중간에 실패하면 지워져야함)
8. 끝
"""

HEADER_SIZE = 64
ENTRY_SIZE = 64
MAX_NAME_SIZE = 15  # the file name is 16 bytes, keep a room for the null terminator


@dataclass(slots=True)
class PackFile:
    name: str
    src_path: Path
    size: int
    unknown_3: int = 0


class TrpPacker:
    def __init__(self, input_dir: Path, output_path: Path) -> None:
        self.INPUT_DIR = input_dir
        self.OUTPUT_PATH = output_path
        self.TEMP_PATH = output_path.with_name(output_path.name + ".tmp")

        self.DEV_FLAG: int = -1
        self.FILE_LIST: list[PackFile] = []
        self.HEADER: TRP_HEADER | None = None
        self.ENTRY_LIST: list[TRP_FILE_ENTRY] = []

    def run(self) -> int:
        log.info("TrpPacker starting")

        # load metadata
        log.info("Load metadata")
        meta_path = self.INPUT_DIR / const.META_FILE_NAME
        if not meta_path.is_file():
            raise TrpPackException(f"Metadata file not found: {meta_path}")
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        if metadata["version"] != 1:
            raise TrpPackException(f"Unknown version: {metadata['version']}")
        if metadata["trp"]["version"] != 2:
            raise TrpPackException(f"Unsupported trp version: {metadata['trp']['version']}")
        if metadata["trp"]["dev_flag"] not in [0, 1]:
            raise TrpPackException(f"Unknown dev_flag: {metadata['trp']['dev_flag']}")

        # set metadata
        self.DEV_FLAG = metadata["trp"]["dev_flag"]
        meta_files: dict[str, int] = {x["name"]: x["unknown_3"] for x in metadata["files"]}

        # collect files
        log.info("Collect files")
        self.FILE_LIST = self._scan_dir(meta_files)

        # check that there is something to pack
        if not self.FILE_LIST:
            raise TrpPackException("No file to pack")

        # make base tables
        entries_end = HEADER_SIZE + (ENTRY_SIZE * len(self.FILE_LIST))
        ofs = entries_end
        for file in self.FILE_LIST:
            self.ENTRY_LIST.append(TRP_FILE_ENTRY(
                FILE_NAME=file.name.encode("utf-8").ljust(16, b"\x00"),
                unknown_1=bytes(20),
                START_OFS=ofs,
                unknown_2=0,
                FILE_SIZE=file.size,
                unknown_3=file.unknown_3,
                PADDING=bytes(12),
            ))
            ofs += get_align16_size(file.size)
        if ofs >= 2 ** 32:
            raise TrpPackException(f"The total size is too large for trp: {ofs}")

        self.HEADER = TRP_HEADER(
            SIGNATURE=0xDCA24D00,
            VERSION=2,
            FILE_SIZE=ofs,
            FILE_COUNT=len(self.FILE_LIST),
            ENTRY_SIZE=ENTRY_SIZE,
            DEV_FLAG=self.DEV_FLAG,
            HASH=bytes(20),
            PADDING=bytes(16),
        )

        self.OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._write_trp(entries_end)
            self.TEMP_PATH.replace(self.OUTPUT_PATH)
        except BaseException:
            self.TEMP_PATH.unlink(missing_ok=True)
            raise

        log.info("TrpPacker finished: %s", self.OUTPUT_PATH)
        return 0

    def _write_trp(self, entries_end: int) -> None:
        assert self.HEADER is not None

        log.info("Write files")
        with BinaryWriter(self.TEMP_PATH) as bw:
            bw.write_zeros(entries_end)
            for file in self.FILE_LIST:
                log.debug("Write file %s", file.src_path)
                with BinaryReader(file.src_path) as br:
                    bw.write_chunks(br.read_chunks(file.size))
                bw.write_align(16)

            # write header and entry list
            bw.seek(0)
            bw.write_bytes(make_header(self.HEADER))
            bw.write_bytes(make_entry_list(self.ENTRY_LIST))
            bw.flush()

            # the HASH field is treated as 0 while calculating
            sha1 = hashlib.sha1()
            with BinaryReader(self.TEMP_PATH) as br:
                for chunk in br.read_chunks(self.HEADER.FILE_SIZE):
                    sha1.update(chunk)
            self.HEADER.HASH = sha1.digest()

            bw.seek(0)
            bw.write_bytes(make_header(self.HEADER))

    def _scan_dir(self, meta_files: dict[str, int]) -> list[PackFile]:
        found: dict[str, PackFile] = {}
        for entry in sorted(self.INPUT_DIR.iterdir(), key=lambda p: p.name.encode("utf-8")):
            if entry.name == const.META_FILE_NAME:
                continue
            if not entry.is_file():
                log.warning("Skip unsupported entry: %s", entry.name)
                continue
            if not entry.name.isascii() or len(entry.name.encode("utf-8")) > MAX_NAME_SIZE:
                raise TrpPackException(f"The file name must be ascii and at most {MAX_NAME_SIZE} bytes: {entry.name}")
            found[entry.name] = PackFile(name=entry.name, src_path=entry, size=entry.stat().st_size)

        # check that every file in the metadata exists
        missing = [name for name in meta_files if name not in found]
        if missing:
            raise TrpPackException(f"{len(missing)} file(s) in the metadata are not found: {', '.join(missing[:5])}{', ...' if len(missing) > 5 else ''}")

        # the files in the metadata come first in its order, the others follow in the name order
        file_list: list[PackFile] = []
        for name, unknown_3 in meta_files.items():
            found[name].unknown_3 = unknown_3
            file_list.append(found[name])
        for name, file in found.items():
            if name not in meta_files:
                log.warning("File is not in the metadata, it is added to the end: %s", name)
                file_list.append(file)
        return file_list
