import logging
from pathlib import Path

from ymtools.src.gop._txt import build_text
from ymtools.src.gop._xlsx import build_workbook
from ymtools.src.gop.exceptions import GopDumpException
from ymtools.src.gop.gop import GOP

log = logging.getLogger(__name__)


"""
gop 덤프 과정 정리
1. gop 파일을 읽는다(구조를 검증하며 위반이 있으면 예외)
2. 컬럼 정보, 메타데이터 트리, 레코드를 해석해서 출력 형식에 맞게 만든다
    - xlsx: 모든 데이터를 담으며 gop-gen의 입력으로 쓸 수 있다
        - GDAT: 1행은 컬럼 이름, 2행부터 레코드. 빈 문자열은 빈 셀, null은 `<null>`, 벡터와 색상은 JSON 배열 문자열, 알 수 없는 타입은 hex 문자열
        - GREC: 컬럼의 Name, Type, TypeId, Offset, Size, Lang
        - GMAT: 메타데이터 트리. A~D열에 노드 이름, E열에 `=`, F열에 값 목록(JSON 배열 문자열)
        - GFIN: version
    - txt: 버전 관리용으로 컬럼 이름과 레코드의 값만 담는다. 형식은 _txt.py 참고
3. 임시 파일에 저장한다
4. 임시파일을 출력 파일로 이름 바꾼다(중간에 실패하면 지워져야함)
5. 끝

출력 경로
- 형식을 지정하지 않으면 xlsx와 txt를 모두 만들며, 출력 경로는 디렉터리이고 파일 이름은 gop 파일과 같다(확장자만 다름)
- 형식을 지정하면 출력 경로는 파일이다. 단 출력 경로가 이미 존재하는 디렉터리이면 위와 같이 gop 파일의 이름을 사용한다
"""


class GopDumper:
    def __init__(self, input_path: Path, output_path: Path, fmt: str | None = None) -> None:
        if not input_path.name.endswith(".gop"):
            raise GopDumpException(f"This is not gop file: {input_path}")
        if fmt not in (None, "xlsx", "txt"):
            raise GopDumpException(f"The output format '{fmt}' is not supported. Use 'xlsx' or 'txt'")

        self.INPUT_PATH = input_path
        if fmt is None or output_path.is_dir():
            if output_path.exists() and not output_path.is_dir():
                raise GopDumpException(f"The output path must be a directory: {output_path}")
            self.OUTPUT_PATHS = {f: output_path / f"{input_path.stem}.{f}" for f in ([fmt] if fmt else ["xlsx", "txt"])}
        else:
            self.OUTPUT_PATHS = {fmt: output_path}

    def run(self) -> int:
        log.info("GopDumper starting")

        if self.INPUT_PATH.resolve() in {path.resolve() for path in self.OUTPUT_PATHS.values()}:
            raise GopDumpException(f"The output path must not be the same as the input path: {self.INPUT_PATH}")

        gop = GOP.read_gop(self.INPUT_PATH)
        log.info(f"Columns: {gop.get_grec().COLUMN_COUNT}, Records: {gop.get_gdat().RECORD_COUNT}")

        temp_paths = {fmt: path.with_name(path.name + ".tmp") for fmt, path in self.OUTPUT_PATHS.items()}
        try:
            for fmt, path in self.OUTPUT_PATHS.items():
                log.info(f"Make {fmt}: {path}")
                path.parent.mkdir(parents=True, exist_ok=True)
                if fmt == "xlsx":
                    build_workbook(gop).save(temp_paths[fmt])
                else:
                    temp_paths[fmt].write_text(build_text(gop), encoding="utf-8", newline="\n")
            for fmt, path in self.OUTPUT_PATHS.items():
                temp_paths[fmt].replace(path)
        except BaseException:
            for temp_path in temp_paths.values():
                temp_path.unlink(missing_ok=True)
            raise

        log.info("GopDumper finished")
        return 0
