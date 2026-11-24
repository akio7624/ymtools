import json
import logging
from pathlib import Path

from ymtools.src import const
from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.trp.exceptions import TrpUnpackException
from ymtools.src.trp.trp import TRP

log = logging.getLogger(__name__)


"""
언팩 과정 정리
1. trp 파일을 읽는다(구조를 검증하며 위반이 있으면 예외)
2. 각 엔트리의 START_OFS에서 FILE_SIZE만큼 읽어 출력 디렉터리에 파일명 그대로 쓴다
3. 팩에 필요한 정보를 메타데이터 파일에 쓴다
    - trp: 버전, DEV_FLAG
    - files: 엔트리 순서대로의 파일명과 unknown_3
4. 끝
"""


class TrpUnpacker:
    def __init__(self, input_path: Path, output_dir: Path) -> None:
        if not input_path.name.lower().endswith(".trp"):
            raise TrpUnpackException(f"This is not trp file: {input_path}")
        self.INPUT_PATH = input_path
        self.OUTPUT_DIR = output_dir

    def run(self) -> int:
        log.info("TrpUnpacker starting")

        trp = TRP.read_trp(self.INPUT_PATH)
        header = trp.get_header()
        entry_list = trp.get_entry_list()
        log.info(f"Files: {len(entry_list)}")

        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path: Path = self.OUTPUT_DIR
        files: list[dict[str, str | int]] = []
        with BinaryReader(self.INPUT_PATH) as br:
            try:
                for i, entry in enumerate(entry_list):
                    if i % 50 == 0:
                        log.info(f"Processing files...({i}/{len(entry_list)})")

                    out_path = self.OUTPUT_DIR / entry.name
                    log.debug("Extract file %s", out_path)
                    if not self._extract_file(br, out_path, entry.START_OFS, entry.FILE_SIZE):
                        return 1
                    files.append({"name": entry.name, "unknown_3": entry.unknown_3})
                log.info(f"Processed {len(entry_list)} files")

                with open(self.OUTPUT_DIR / const.META_FILE_NAME, "w", encoding="utf-8") as f:
                    json.dump({
                        "version": 1,
                        "tool_version": const.VERSION,
                        "trp": {"version": header.VERSION, "dev_flag": header.DEV_FLAG},
                        "files": files,
                    }, f, indent=2, ensure_ascii=False)
            except EOFError as e:
                log.error("Failed to extract %s (%s: %s)", out_path, type(e).__name__, e)
                return 1

        log.info("TrpUnpacker finished")
        return 0

    def _extract_file(self, br: BinaryReader, out_path: Path, ofs: int, size: int) -> bool:
        br.seek(ofs)
        written = 0
        with open(out_path, "wb") as f:
            for chunk in br.read_chunks(size):
                written += f.write(chunk)
        if written != size:
            log.error(f"Unexpected file size: {written} while extracting {out_path}")
            return False
        return True
