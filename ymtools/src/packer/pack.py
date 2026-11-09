import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ymtools.src import const
from ymtools.src.packer.exceptions import PackerException
from ymtools.src.structure._tables import ENDILTLE, FS_SEGMENT, GENEEOF, GENESTRT, PACKFSLS, PACKHEDR, PACKTOC, TOC_SEGMENT
from ymtools.src.structure.utils import get_align16_size

log = logging.getLogger(__name__)


"""
패킹 과정 정리
1. 루트 및 FS에서 필요한 문자열 수집 및 세그먼트 데이터 정렬
2. 가능한 정보들로 루트 및 FS 메타데이터 테이블 객체 먼저 생성
3. 각 테이블을 바이너리로 변환하여 사이즈 모두 더한다
4. 더한 합을 2048에 맞춰 패딩했다 가정할 때 그 지점부터 루트 파일이 시작되는 위치이다. 이 위치를 ROOT_FILES_OFS에 기록한다
5. 임시 파일에 해당 사이즈만큼 앞에 빈 공간 만들고, 루트 파일 시작 지점부터 실제로 파일을 바로 순차적으로 쓴다
6. 각 파일을 쓰면서 압축 크기 등을 계산하며 매번 해당하는 세그먼트의 미완성 필드를 채워주고, 각 파일에 대한 패딩을 적용한다
7. 루트 파일 쓰기가 끝나고, FS가 있다면 2048로 다시 패딩 추가한다
8. 각 FS에 대해 반복한다
  1. 현재 FS의 시작 오프셋을 PACKFSLS의 FS_ABSOLUTE_OFS에 기록한다
  2. 현재 FS의 테이블들을 바이너리로 변환하여 사이즈 모두 더한다
  3. 별도의 패딩은 필요없고, 출력 파일에 해당 크기만큼 예약 공간 확보한다
  4. 파일 나열되는 지점에서 각 파일을 기록하며 FS의 PACKFSHD의 세그먼트를 갱신하고, 각 파일에 대해 패딩을 적용한다
  5. 파일이 모두 나열되면 현재 FS의 테이블들을 예약된 공간에 기록하고 flush한다
  6. 현재 FS의 시작점~기록이 끝난 지점의 크기인 FS_SIZE와 그 구간의 해시를 계산한 FS_HASH를 PACKFSLS의 세그먼트에 적용한다
  7. 현재 FS의 마지막 지점에 대해 FS_PAD_TYPE에 따른 패딩을 추가한다(다만 마지막 FS면 하지 않는다)
9. 모든 FS가 나열되면 루트 메타테이블들의 객체를 다시 바이너리로 변환해 파일 앞 예약된 공간에 한번에 써준다.
10. 임시파일을 출력 파일로 이름 바꾼다(중간에 실패하면 지워져야함)
11. 끝
"""


@dataclass(slots=True)
class PackNode:
    name: str
    is_dir: bool
    children: list["PackNode"] = field(default_factory=list)  # directory only
    src_path: Path | None = None  # file only
    size: int = 0  # file only
    compress: bool = False  # file only
    seg: TOC_SEGMENT | None = None  # segment of this node in PACKTOC, root nodes only


class Packer:
    def __init__(self, input_dir: Path, output_path: Path) -> None:
        self.INPUT_DIR = input_dir
        self.OUTPUT_PATH = output_path

        self.PACKAGE_NAME: str = ""
        self.FS_PAD_TYPE: int = -1
        self.ROOT_COMPRESS_FILES: set[str] = set()
        self.FS_COMPRESS_FILES: set[str] = set()

        self.ROOT_NODES: list[PackNode] = []
        self.TOC_SEG_COUNT = -1
        self.FS_NODES: dict[str, list[PackNode]] = {}  # key: fs name, in name order
        self.FS_SEG_COUNT = -1

        self.ROOT_TABLES: dict[str, Any] = {
                "ENDILTLE": None,
                "PACKHEDR": None,
                "PACKTOC": None,
                "PACKFSLS": None,
                "GENESTRT": None,
                "GENEEOF": None,
            }
        self.FS_TABLES: dict[str, dict[str, Any]] = {}  # key: FS name, value: FS table dict

    def run(self) -> int:
        log.info("Packer starting")

        # load metadata
        log.info("Load metadata")
        with open(self.INPUT_DIR / const.META_FILE_NAME, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        if metadata["version"] != 1:
            raise PackerException(f"Unknown version: {metadata['version']}")
        if not metadata["package"]["name"]:
            raise PackerException(f"Unknown package name: {metadata['package']['name']}")
        if metadata["package"]["fs_pad_type"] not in [1, 2]:
            raise PackerException(f"Unknown fs_pad_type: {metadata['package']['fs_pad_type']}")

        # set metadata
        self.PACKAGE_NAME = metadata["package"]["name"]
        self.FS_PAD_TYPE = metadata["package"]["fs_pad_type"]
        self.ROOT_COMPRESS_FILES = {x["path"] for x in metadata["root"]["compress"]}
        self.FS_COMPRESS_FILES = {x["path"] for x in metadata["fs"]["compress"]}

        # collect root files
        log.info("Collect root files")
        root_dir = self.INPUT_DIR / "ROOT"
        if root_dir.is_dir():
            self.ROOT_NODES = self._scan_dir(root_dir, root_dir)
        else:
            log.warning("There is no ROOT directory, the apk will have no root files")

        # collect fs files
        log.info("Collect fs files")
        fs_root_dir = self.INPUT_DIR / "FS"
        if fs_root_dir.is_dir():
            for fs_dir in sorted(fs_root_dir.iterdir(), key=lambda p: p.name.encode("utf-8")):
                if not fs_dir.is_dir():
                    log.warning("Skip file in FS directory: FS/%s", fs_dir.name)
                    continue
                nodes = self._scan_fs(fs_dir)
                if not nodes:
                    log.warning("Skip file set without files: %s", fs_dir.name)
                    continue
                self.FS_NODES[fs_dir.name] = nodes
        else:
            log.warning("There is no FS directory, the apk will have no file sets")

        # check that there is something to pack
        if not self.ROOT_NODES and not self.FS_NODES:
            raise PackerException("No file to pack")

        self.TOC_SEG_COUNT = 1 + self._count_nodes(self.ROOT_NODES)
        self.FS_SEG_COUNT = len(self.FS_NODES)

        # make base metadata tables for root
        self.ROOT_TABLES["ENDILTLE"] = ENDILTLE(
            SIGNATURE=b"ENDILTLE",
            TABLE_SIZE=0
        )

        self.ROOT_TABLES["PACKHEDR"] = PACKHEDR(
            SIGNATURE=b"PACKHEDR",
            TABLE_SIZE=32,
            unknown_1=65536,
            NAME_IDX=0,
            ROOT_FILES_OFS=-1,
            FS_PAD_TYPE=self.FS_PAD_TYPE,
            HASH=b"\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0",
        )

        self.ROOT_TABLES["PACKTOC"] = PACKTOC(
            SIGNATURE=b"PACKTOC ",
            TABLE_SIZE=get_align16_size(16 + (40 * self.TOC_SEG_COUNT)),
            TOC_SEG_SIZE=40,
            TOC_SEG_COUNT=self.TOC_SEG_COUNT,
            TOC_SEG_LIST_OFS=16,
            unknown_1=0,
            TOC_SEG_LIST=self._make_toc_seg_list(),
        )

        self.ROOT_TABLES["PACKFSLS"] = PACKFSLS(
            SIGNATURE=b"PACKFSLS",
            TABLE_SIZE=get_align16_size(16 + (40 * self.FS_SEG_COUNT)),
            FS_SEG_COUNT=self.FS_SEG_COUNT,
            FS_SEG_SIZE=40,
            FS_SEG_LIST_OFS=16,
            unknown_1=0,
            FS_SEG_LIST=self._make_fs_seg_list(),
        )

        self.ROOT_TABLES["GENESTRT"] = self._make_genestrt(list(self._make_root_name_idx()))

        self.ROOT_TABLES["GENEEOF"] = GENEEOF(
            SIGNATURE=b"GENEEOF ",
            TABLE_SIZE=0
        )

        return 0

    def _scan_dir(self, dir_path: Path, root_dir: Path) -> list[PackNode]:
        nodes: list[PackNode] = []
        for entry in sorted(dir_path.iterdir(), key=lambda p: p.name.encode("utf-8")):
            rel_path = entry.relative_to(root_dir).as_posix()

            if entry.is_dir():
                children = self._scan_dir(entry, root_dir)
                if not children:
                    log.warning("Skip empty directory: %s", rel_path)
                    continue
                nodes.append(PackNode(name=entry.name, is_dir=True, children=children))
            elif entry.is_file():
                size = entry.stat().st_size
                if size == 0:
                    log.warning("Skip empty file: ROOT/%s", rel_path)
                    continue
                nodes.append(PackNode(
                    name=entry.name,
                    is_dir=False,
                    src_path=entry,
                    size=size,
                    compress=rel_path in self.ROOT_COMPRESS_FILES)
                )
            else:
                log.warning("Skip unsupported entry: %s", rel_path)
        return nodes

    def _scan_fs(self, fs_dir: Path) -> list[PackNode]:
        nodes: list[PackNode] = []
        for entry in fs_dir.rglob("*"):
            if not entry.is_file():
                continue
            rel_path = entry.relative_to(fs_dir).as_posix()
            size = entry.stat().st_size
            if size == 0:
                log.warning("Skip empty file: FS/%s/%s", fs_dir.name, rel_path)
                continue
            nodes.append(PackNode(
                name=rel_path,
                is_dir=False,
                src_path=entry,
                size=size,
                compress=f"{fs_dir.name}/{rel_path}" in self.FS_COMPRESS_FILES)
            )
        nodes.sort(key=lambda n: n.name.encode("utf-8"))
        return nodes

    def _count_nodes(self, nodes):
        return sum(1 + (self._count_nodes(n.children) if n.is_dir else 0) for n in nodes)

    def _make_toc_seg_list(self) -> list[TOC_SEGMENT]:
        name_idx: dict[str, int] = {self.PACKAGE_NAME: 0, "": 1}

        def collect_names(nodes: list[PackNode]) -> None:
            for node in nodes:
                if node.name not in name_idx:
                    name_idx[node.name] = len(name_idx)
                if node.is_dir:
                    collect_names(node.children)

        collect_names(self.ROOT_NODES)

        def make_seg(node: PackNode) -> TOC_SEGMENT:
            if node.is_dir:
                seg = TOC_SEGMENT(
                    IDENTIFIER=1,
                    COMPRESS_TYPE=0,
                    unknown_1=0,
                    NAME_IDX=name_idx[node.name],
                    PACKAGE_NAME_IDX=0,
                    unknown_2=0,
                )
            else:
                seg = TOC_SEGMENT(
                    IDENTIFIER=0,
                    COMPRESS_TYPE=2 if node.compress else 0,
                    unknown_1=0,
                    NAME_IDX=name_idx[node.name],
                    PACKAGE_NAME_IDX=0,
                    unknown_2=0,
                    FILE_SIZE=node.size,  # uncompressed size
                )
            node.seg = seg
            return seg

        seg_list: list[TOC_SEGMENT] = [TOC_SEGMENT(
            IDENTIFIER=1,
            COMPRESS_TYPE=0,
            unknown_1=0,
            NAME_IDX=name_idx[""],
            PACKAGE_NAME_IDX=0,
            unknown_2=0,
        )]

        def layout(seg: TOC_SEGMENT, nodes: list[PackNode]) -> None:
            seg.ENTRY_INDEX = len(seg_list) if nodes else 0
            seg.ENTRY_COUNT = len(nodes)

            children = [make_seg(node) for node in nodes]
            seg_list.extend(children)
            for child, node in zip(children, nodes):
                if node.is_dir:
                    layout(child, node.children)

        layout(seg_list[0], self.ROOT_NODES)

        assert len(seg_list) == self.TOC_SEG_COUNT
        return seg_list

    def _make_root_name_idx(self) -> dict[str, int]:
        name_idx: dict[str, int] = {self.PACKAGE_NAME: 0, "": 1}

        def collect_names(nodes: list[PackNode]) -> None:
            for node in nodes:
                if node.name not in name_idx:
                    name_idx[node.name] = len(name_idx)
                if node.is_dir:
                    collect_names(node.children)

        collect_names(self.ROOT_NODES)
        for fs_name in self.FS_NODES:
            if fs_name not in name_idx:
                name_idx[fs_name] = len(name_idx)
        return name_idx

    def _make_fs_seg_list(self) -> list[FS_SEGMENT]:
        name_idx = self._make_root_name_idx()

        return [FS_SEGMENT(
            NAME_IDX=name_idx[fs_name],
            PACKAGE_NAME_IDX=0,
            FS_ABSOLUTE_OFS=0,
            FS_SIZE=0,
            FS_HASH=b"\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0",
        ) for fs_name in self.FS_NODES]

    def _make_genestrt(self, string_list: list[str]) -> GENESTRT:
        string_ofs_list: list[int] = []
        string_list_size = 0
        for s in string_list:
            string_ofs_list.append(string_list_size)
            string_list_size += len(s.encode("utf-8")) + 1

        string_list_ofs = get_align16_size(16 + (4 * len(string_list)))
        table_size = get_align16_size(string_list_ofs + string_list_size)

        return GENESTRT(
            SIGNATURE=b"GENESTRT",
            TABLE_SIZE=table_size,
            STRING_COUNT=len(string_list),
            STRING_OFS_LIST_OFS=16,
            STRING_LIST_OFS=string_list_ofs,
            TABLE_SIZE_2=table_size,
            STRING_OFS_LIST=string_ofs_list,
            STRING_OFS_LIST_PAD=bytes(string_list_ofs - (16 + (4 * len(string_list)))),
            STRING_LIST=string_list,
            STRING_LIST_PAD=bytes(table_size - string_list_ofs - string_list_size),
        )
