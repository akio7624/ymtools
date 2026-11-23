import logging
from pathlib import Path

from ymtools.src.gop._xlsx import build_workbook
from ymtools.src.gop.exceptions import GopException
from ymtools.src.gop.gop import GOP

__all__ = ["GopDumper"]
log = logging.getLogger(__name__)


"""
gop 덤프 과정 정리
1. gop 파일을 읽는다(모든 테이블을 읽고 구조를 확인한다)
2. 메타데이터 트리, 컬럼 정보, 레코드를 해석한다
3. xlsx 워크북을 만든다(GDAT, GREC, GMAT, GFIN)
4. 임시 파일에 저장한다
5. 임시파일을 출력 파일로 이름 바꾼다(중간에 실패하면 지워져야함)
6. 끝
"""


class GopDumper:
    def __init__(self, input_path: Path, output_path: Path, fmt: str = "xlsx") -> None:
        self.INPUT_PATH = input_path
        self.OUTPUT_PATH = output_path
        self.TEMP_PATH = output_path.with_name(output_path.name + ".tmp")
        self.FORMAT = fmt

    def run(self) -> int:
        log.info("GopDumper starting")

        if self.FORMAT != "xlsx":
            raise GopException(f"The output format '{self.FORMAT}' is not supported yet. Only 'xlsx' is available")
        if self.OUTPUT_PATH.resolve() == self.INPUT_PATH.resolve():
            raise GopException(f"The output path must not be the same as the input path: {self.OUTPUT_PATH}")

        # read gop file
        gop = GOP.read_gop(self.INPUT_PATH)
        log.info(f"Columns: {len(gop.get_columns())}, Records: {gop.get_record_count()}")

        # make xlsx
        log.info("Make xlsx")
        wb = build_workbook(gop)

        self.OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            log.info("Write xlsx")
            wb.save(self.TEMP_PATH)
            self.TEMP_PATH.replace(self.OUTPUT_PATH)
        except BaseException:
            self.TEMP_PATH.unlink(missing_ok=True)
            raise

        log.info("GopDumper finished: %s", self.OUTPUT_PATH)
        return 0
