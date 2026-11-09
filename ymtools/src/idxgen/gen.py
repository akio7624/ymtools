import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ymtools.src.binutils.BinaryWriter import BinaryWriter
from ymtools.src.idxgen.exceptions import IdxGenException
from ymtools.src.structure import ENDILTLE, FS_SEGMENT, GENEEOF, PACKFSLS, PACKHEDR, PACKTOC, TOC_SEGMENT
from ymtools.src.structure import make_endiltle, make_geneeof, make_genestrt, make_packfsls, make_packhedr, make_packtoc
from ymtools.src.structure.apk import APK
from ymtools.src.structure.utils import build_genestrt, get_align16_size

log = logging.getLogger(__name__)


"""
idx 생성 과정 정리
1. 입력 apk를 모두 읽고 apk의 경로 문자열 기준으로 정렬한다(경로 문자열이 같은 apk가 있으면 예외)
2. 각 apk의 TOC를 경로 기준으로 하나의 트리로 병합한다(같은 경로의 파일이 여러 apk에 있으면 예외)
3. 각 apk의 FS를 모은다(같은 이름의 FS가 여러 apk에 있으면 예외)
4. 문자열을 수집한다. apk 경로, 빈 문자열, TOC 트리의 이름, FS 이름 순서이다
5. 테이블 객체를 생성한다. apk의 값을 그대로 복사하므로 지연 계산이 필요한 필드는 없다
6. 임시 파일에 테이블을 순서대로 기록한다
7. 임시파일을 출력 파일로 이름 바꾼다(중간에 실패하면 지워져야함)
8. 끝
"""


@dataclass(slots=True)
class IdxNode:
    name: str
    is_dir: bool
    children: dict[str, "IdxNode"] = field(default_factory=dict)  # directory only
    apk_idx: int = 0  # file only, index of the apk that has this file
    seg: TOC_SEGMENT | None = None  # file only, segment of this file in the apk


class IdxGenerator:
    def __init__(self, input_paths: list[Path], output_path: Path) -> None:
        self.INPUT_PATHS = input_paths
        self.OUTPUT_PATH = output_path
        self.TEMP_PATH = output_path.with_name(output_path.name + ".tmp")

        self.APKS: list[APK] = []
        self.PACKAGE_NAMES: list[str] = []
        self.ROOT_NODE = IdxNode(name="", is_dir=True)
        self.FS_LIST: list[tuple[str, int, FS_SEGMENT]] = []  # fs name, index of the apk, segment in the apk
        self.NAME_IDX: dict[str, int] = {}

        self.TABLES: dict[str, Any] = {
            "ENDILTLE": None,
            "PACKHEDR": [],
            "PACKTOC": None,
            "PACKFSLS": None,
            "GENESTRT": None,
            "GENEEOF": None,
        }

    def run(self) -> int:
        log.info("IdxGenerator starting")

        # read apk files
        log.info("Read apk files")
        if self.OUTPUT_PATH.resolve() in {path.resolve() for path in self.INPUT_PATHS}:
            raise IdxGenException(f"The output path must not be the same as an input path: {self.OUTPUT_PATH}")
        self.APKS = [APK.read_apk(path) for path in self.INPUT_PATHS]
        self.APKS.sort(key=lambda apk: apk.get_package_name().encode("utf-8"))
        self.PACKAGE_NAMES = [apk.get_package_name() for apk in self.APKS]

        duplicated = sorted({name for name in self.PACKAGE_NAMES if self.PACKAGE_NAMES.count(name) > 1})
        if duplicated:
            raise IdxGenException(f"The paths of the apk must not be duplicated: {', '.join(duplicated)}")

        # merge toc of the apk files
        log.info("Merge toc")
        for apk_idx, apk in enumerate(self.APKS):
            self._merge_toc(apk_idx, apk)

        # collect fs of the apk files
        log.info("Collect fs")
        fs_owner: dict[str, int] = {}
        for apk_idx, apk in enumerate(self.APKS):
            string_list = apk.get_string_list()
            for file_set in apk.get_file_sets():
                fs_name = string_list[file_set.SEGMENT.NAME_IDX]
                if fs_name in fs_owner:
                    raise IdxGenException(f"The FS '{fs_name}' exists in both the apk '{self.PACKAGE_NAMES[fs_owner[fs_name]]}' and '{self.PACKAGE_NAMES[apk_idx]}'")
                fs_owner[fs_name] = apk_idx
                self.FS_LIST.append((fs_name, apk_idx, file_set.SEGMENT))

        self.NAME_IDX = self._make_name_idx()

        # make metadata tables
        self.TABLES["ENDILTLE"] = ENDILTLE(
            SIGNATURE=b"ENDILTLE",
            TABLE_SIZE=0
        )

        self.TABLES["PACKHEDR"] = [PACKHEDR(
            SIGNATURE=b"PACKHEDR",
            TABLE_SIZE=32,
            unknown_1=apk.get_packhedr().unknown_1,
            NAME_IDX=apk_idx,
            ROOT_FILES_OFS=apk.get_packhedr().ROOT_FILES_OFS,
            FS_PAD_TYPE=apk.get_packhedr().FS_PAD_TYPE,
            HASH=apk.get_packhedr().HASH,
        ) for apk_idx, apk in enumerate(self.APKS)]

        toc_seg_list = self._make_toc_seg_list()
        self.TABLES["PACKTOC"] = PACKTOC(
            SIGNATURE=b"PACKTOC ",
            TABLE_SIZE=get_align16_size(16 + (40 * len(toc_seg_list))),
            TOC_SEG_SIZE=40,
            TOC_SEG_COUNT=len(toc_seg_list),
            TOC_SEG_LIST_OFS=16,
            unknown_1=0,
            TOC_SEG_LIST=toc_seg_list,
        )

        fs_seg_list = self._make_fs_seg_list()
        self.TABLES["PACKFSLS"] = PACKFSLS(
            SIGNATURE=b"PACKFSLS",
            TABLE_SIZE=get_align16_size(16 + (40 * len(fs_seg_list))),
            FS_SEG_COUNT=len(fs_seg_list),
            FS_SEG_SIZE=40,
            FS_SEG_LIST_OFS=16,
            unknown_1=0,
            FS_SEG_LIST=fs_seg_list,
        )

        self.TABLES["GENESTRT"] = build_genestrt(list(self.NAME_IDX))

        self.TABLES["GENEEOF"] = GENEEOF(
            SIGNATURE=b"GENEEOF ",
            TABLE_SIZE=0
        )

        self.OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._write_idx()
            self.TEMP_PATH.replace(self.OUTPUT_PATH)
        except BaseException:
            self.TEMP_PATH.unlink(missing_ok=True)
            raise

        log.info("IdxGenerator finished: %s", self.OUTPUT_PATH)
        return 0

    def _write_idx(self) -> None:
        log.info("Write idx")
        with BinaryWriter(self.TEMP_PATH) as bw:
            bw.write_bytes(make_endiltle(self.TABLES["ENDILTLE"]))
            for packhedr in self.TABLES["PACKHEDR"]:
                bw.write_bytes(make_packhedr(packhedr))
            bw.write_bytes(make_packtoc(self.TABLES["PACKTOC"]))
            bw.write_bytes(make_packfsls(self.TABLES["PACKFSLS"]))
            bw.write_bytes(make_genestrt(self.TABLES["GENESTRT"]))
            bw.write_bytes(make_geneeof(self.TABLES["GENEEOF"]))

    def _merge_toc(self, apk_idx: int, apk: APK) -> None:
        toc_seg_list = apk.get_toc_seg_list()
        string_list = apk.get_string_list()

        def merge(node: IdxNode, seg: TOC_SEGMENT, path: str) -> None:
            for child_seg in toc_seg_list[seg.ENTRY_INDEX:seg.ENTRY_INDEX + seg.ENTRY_COUNT]:
                name = string_list[child_seg.NAME_IDX]
                child_path = f"{path}{name}"
                child = node.children.get(name)

                if child_seg.IDENTIFIER == 1:
                    if child is None:
                        child = node.children[name] = IdxNode(name=name, is_dir=True)
                    elif not child.is_dir:
                        raise IdxGenException(f"'{child_path}' is a file in the apk '{self.PACKAGE_NAMES[child.apk_idx]}' but a directory in '{self.PACKAGE_NAMES[apk_idx]}'")
                    merge(child, child_seg, f"{child_path}/")
                else:
                    if child is not None:
                        if child.is_dir:
                            raise IdxGenException(f"'{child_path}' is a file in the apk '{self.PACKAGE_NAMES[apk_idx]}' but a directory in another apk")
                        raise IdxGenException(f"'{child_path}' exists in both the apk '{self.PACKAGE_NAMES[child.apk_idx]}' and '{self.PACKAGE_NAMES[apk_idx]}'")
                    node.children[name] = IdxNode(name=name, is_dir=False, apk_idx=apk_idx, seg=child_seg)

        merge(self.ROOT_NODE, toc_seg_list[0], "")

    def _sorted_children(self, node: IdxNode) -> list[IdxNode]:
        return sorted(node.children.values(), key=lambda child: child.name.encode("utf-8"))

    def _make_name_idx(self) -> dict[str, int]:
        name_idx: dict[str, int] = {}

        def add(name: str) -> None:
            if name not in name_idx:
                name_idx[name] = len(name_idx)

        def collect_names(node: IdxNode) -> None:
            for child in self._sorted_children(node):
                add(child.name)
                if child.is_dir:
                    collect_names(child)

        for package_name in self.PACKAGE_NAMES:
            add(package_name)
        add("")
        collect_names(self.ROOT_NODE)
        for fs_name, _, _ in self.FS_LIST:
            add(fs_name)
        return name_idx

    def _make_toc_seg_list(self) -> list[TOC_SEGMENT]:
        name_idx = self.NAME_IDX

        def make_seg(node: IdxNode) -> TOC_SEGMENT:
            if node.is_dir:
                return TOC_SEGMENT(
                    IDENTIFIER=1,
                    COMPRESS_TYPE=0,
                    unknown_1=0,
                    NAME_IDX=name_idx[node.name],
                    PACKAGE_NAME_IDX=0,
                    unknown_2=0,
                )
            return TOC_SEGMENT(
                IDENTIFIER=0,
                COMPRESS_TYPE=node.seg.COMPRESS_TYPE,
                unknown_1=0,
                NAME_IDX=name_idx[node.name],
                PACKAGE_NAME_IDX=self.TABLES["PACKHEDR"][node.apk_idx].NAME_IDX,
                unknown_2=0,
                FILE_ABSOLUTE_OFS=node.seg.FILE_ABSOLUTE_OFS,
                FILE_SIZE=node.seg.FILE_SIZE,
                FILE_ZSIZE=node.seg.FILE_ZSIZE,
            )

        seg_list: list[TOC_SEGMENT] = [make_seg(self.ROOT_NODE)]

        def layout(seg: TOC_SEGMENT, node: IdxNode) -> None:
            children = self._sorted_children(node)
            seg.ENTRY_INDEX = len(seg_list) if children else 0
            seg.ENTRY_COUNT = len(children)

            child_segs = [make_seg(child) for child in children]
            seg_list.extend(child_segs)
            for child_seg, child in zip(child_segs, children):
                if child.is_dir:
                    layout(child_seg, child)

        layout(seg_list[0], self.ROOT_NODE)

        return seg_list

    def _make_fs_seg_list(self) -> list[FS_SEGMENT]:
        return [FS_SEGMENT(
            NAME_IDX=self.NAME_IDX[fs_name],
            PACKAGE_NAME_IDX=self.TABLES["PACKHEDR"][apk_idx].NAME_IDX,
            FS_ABSOLUTE_OFS=seg.FS_ABSOLUTE_OFS,
            FS_SIZE=seg.FS_SIZE,
            FS_HASH=seg.FS_HASH,
        ) for fs_name, apk_idx, seg in sorted(self.FS_LIST, key=lambda fs: fs[0].encode("utf-8"))]
