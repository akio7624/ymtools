import logging
from pathlib import Path

from ymtools.src.gop._xlsx import build_workbook
from ymtools.src.gop.exceptions import GopDumpException
from ymtools.src.gop.gop import GOP

log = logging.getLogger(__name__)


"""
gop 덤프 과정 정리
1. gop 파일을 읽는다(구조를 검증하며 위반이 있으면 예외)
2. 컬럼 정보, 메타데이터 트리, 레코드를 해석해서 xlsx 워크북을 만든다
    - GDAT: 1행은 컬럼 이름, 2행부터 레코드. 빈 문자열은 빈 셀, null은 `<null>`, 벡터와 색상은 JSON 배열 문자열, 알 수 없는 타입은 hex 문자열
    - GREC: 컬럼의 Name, Type, TypeId, Offset, Size, Lang
    - GMAT: 메타데이터 트리. A~D열에 노드 이름, E열에 `=`, F열에 값 목록(JSON 배열 문자열)
    - GFIN: version
3. 임시 파일에 저장한다
4. 임시파일을 출력 파일로 이름 바꾼다(중간에 실패하면 지워져야함)
5. 끝
"""


class GopDumper:
    def __init__(self, input_path: Path, output_path: Path, fmt: str = "xlsx") -> None:
        if not input_path.name.endswith(".gop"):
            raise GopDumpException(f"This is not gop file: {input_path}")
        if fmt != "xlsx":
            raise GopDumpException(f"The output format '{fmt}' is not supported yet. Only 'xlsx' is available")
        self.INPUT_PATH = input_path
        self.OUTPUT_PATH = output_path
        self.TEMP_PATH = output_path.with_name(output_path.name + ".tmp")

    def run(self) -> int:
        log.info("GopDumper starting")

        if self.OUTPUT_PATH.resolve() == self.INPUT_PATH.resolve():
            raise GopDumpException(f"The output path must not be the same as the input path: {self.OUTPUT_PATH}")

        gop = GOP.read_gop(self.INPUT_PATH)
        log.info(f"Columns: {gop.get_grec().COLUMN_COUNT}, Records: {gop.get_gdat().RECORD_COUNT}")

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
