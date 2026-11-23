import hashlib
import json
import logging
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ymtools.src import const
from ymtools.src.apkidx.packer.exceptions import PackerException
from ymtools.src.apkidx.structure import ENDILTLE, FS_FILE_SEG, FS_SEGMENT, GENEEOF, PACKFSHD, PACKFSLS, PACKHEDR, PACKTOC, TOC_SEGMENT
from ymtools.src.apkidx.structure import make_endiltle, make_geneeof, make_genestrt, make_packfshd, make_packfsls, make_packhedr, make_packtoc
from ymtools.src.apkidx.structure.utils import build_genestrt, get_align16_size
from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.binutils.BinaryWriter import BinaryWriter

log = logging.getLogger(__name__)


"""
패킹 과정 정리
1. 루트 및 FS에서 필요한 문자열 수집 및 세그먼트 데이터 정렬
2. 가능한 정보들로 루트 및 FS 메타데이터 테이블 객체 먼저 생성
3. 각 루트 테이블을 바이너리로 변환하여 사이즈 모두 더한다
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
    seg: TOC_SEGMENT | FS_FILE_SEG | None = None  # segment of this node, TOC_SEGMENT for root nodes and FS_FILE_SEG for fs nodes


class Packer:
    def __init__(self, input_dir: Path, output_path: Path) -> None:
        self.INPUT_DIR = input_dir
        self.OUTPUT_PATH = output_path
        self.TEMP_PATH = output_path.with_name(output_path.name + ".tmp")

        self.PACKAGE_NAME: str = ""
        self.FS_PAD_TYPE: int = -1
        self.ROOT_COMPRESS_FILES: set[str] = set()
        self.FS_COMPRESS_FILES: set[str] = set()

        self.ROOT_NODES: list[PackNode] = []
        self.ROOT_NAME_IDX: dict[str, int] = {}
        self.TOC_SEG_COUNT = -1
        self.FS_NODES: dict[str, list[PackNode]] = {}
        self.FS_SEG_COUNT = -1

        self.ROOT_TABLES: dict[str, Any] = {
                "ENDILTLE": None,
                "PACKHEDR": None,
                "PACKTOC": None,
                "PACKFSLS": None,
                "GENESTRT": None,
                "GENEEOF": None,
            }
        self.FS_TABLES: dict[str, dict[str, Any]] = {}
        self.ROOT_TABLES_SIZE = -1
        self.ROOT_FILES_OFS = -1

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

        # check that every compressed file in the metadata exists
        missing_root = sorted(self.ROOT_COMPRESS_FILES - set(self._iter_paths(self.ROOT_NODES)))
        fs_paths = {f"{fs_name}/{node.name}" for fs_name, nodes in self.FS_NODES.items() for node in nodes}
        missing_fs = sorted(self.FS_COMPRESS_FILES - fs_paths)
        if missing_root or missing_fs:
            missing = [f"ROOT/{path}" for path in missing_root] + [f"FS/{path}" for path in missing_fs]
            raise PackerException(f"{len(missing)} compressed file(s) in the metadata are not found: {', '.join(missing[:5])}{', ...' if len(missing) > 5 else ''}")

        self.ROOT_NAME_IDX = self._make_root_name_idx()
        toc_seg_list = self._make_toc_seg_list()
        self.TOC_SEG_COUNT = len(toc_seg_list)
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
            ROOT_FILES_OFS=0,
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
            TOC_SEG_LIST=toc_seg_list,
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

        self.ROOT_TABLES["GENESTRT"] = build_genestrt(list(self.ROOT_NAME_IDX))

        self.ROOT_TABLES["GENEEOF"] = GENEEOF(
            SIGNATURE=b"GENEEOF ",
            TABLE_SIZE=0
        )

        self.ROOT_TABLES_SIZE = (
            len(make_endiltle(self.ROOT_TABLES["ENDILTLE"]))
            + len(make_packhedr(self.ROOT_TABLES["PACKHEDR"]))
            + len(make_packtoc(self.ROOT_TABLES["PACKTOC"]))
            + len(make_packfsls(self.ROOT_TABLES["PACKFSLS"]))
            + len(make_genestrt(self.ROOT_TABLES["GENESTRT"]))
            + len(make_geneeof(self.ROOT_TABLES["GENEEOF"]))
        )
        self.ROOT_FILES_OFS = (self.ROOT_TABLES_SIZE + 2047) // 2048 * 2048
        self.ROOT_TABLES["PACKHEDR"].ROOT_FILES_OFS = self.ROOT_FILES_OFS

        # make base metadata tables for each fs
        for fs_name, nodes in self.FS_NODES.items():
            genestrt = build_genestrt([node.name for node in nodes])
            packfshd_table_size = get_align16_size(32 + (32 * len(nodes)))

            self.FS_TABLES[fs_name] = {
                "ENDILTLE": ENDILTLE(
                    SIGNATURE=b"ENDILTLE",
                    TABLE_SIZE=0
                ),
                "PACKFSHD": PACKFSHD(
                    SIGNATURE=b"PACKFSHD",
                    TABLE_SIZE=packfshd_table_size,
                    unknown_1=65536,
                    FILE_SEG_SIZE=32,
                    FILE_SEG_COUNT=len(nodes),
                    FS_FILE_SEG_LIST_OFS=32,
                    GENEEOF_OFS=16 + (16 + packfshd_table_size) + (16 + genestrt.TABLE_SIZE),
                    unknown_2=0,
                    unknown_3=0,
                    unknown_4=0,
                    FS_FILE_SEG_LIST=self._make_fs_file_seg_list(nodes),
                ),
                "GENESTRT": genestrt,
                "GENEEOF": GENEEOF(
                    SIGNATURE=b"GENEEOF ",
                    TABLE_SIZE=0
                ),
            }

        self.OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._write_apk()
            self.TEMP_PATH.replace(self.OUTPUT_PATH)
        except BaseException:
            self.TEMP_PATH.unlink(missing_ok=True)
            raise

        log.info("Packer finished: %s", self.OUTPUT_PATH)
        return 0

    def _write_apk(self) -> None:
        # write root files
        log.info("Write root files")
        with BinaryWriter(self.TEMP_PATH) as bw:
            bw.write_zeros(self.ROOT_FILES_OFS)
            for node in self._iter_files(self.ROOT_NODES):
                log.debug("Write root file %s", node.src_path)
                node.seg.FILE_ABSOLUTE_OFS = bw.tell()
                stored_size = bw.write_chunks(self._make_file_chunks(node))
                if node.compress:
                    node.seg.FILE_ZSIZE = stored_size
                bw.write_align(512)

            if self.FS_NODES:
                bw.write_align(2048)

            # write fs
            for i, (fs_seg, (fs_name, nodes)) in enumerate(zip(self.ROOT_TABLES["PACKFSLS"].FS_SEG_LIST, self.FS_NODES.items())):
                log.info("Write fs %s", fs_name)
                tables = self.FS_TABLES[fs_name]
                fs_seg.FS_ABSOLUTE_OFS = bw.tell()

                fs_tables_size = (
                    len(make_endiltle(tables["ENDILTLE"]))
                    + len(make_packfshd(tables["PACKFSHD"]))
                    + len(make_genestrt(tables["GENESTRT"]))
                    + len(make_geneeof(tables["GENEEOF"]))
                )
                bw.write_zeros(fs_tables_size)

                for node in nodes:
                    log.debug("Write fs file %s", node.src_path)
                    node.seg.FILE_OFS = bw.tell() - fs_seg.FS_ABSOLUTE_OFS
                    stored_size = bw.write_chunks(self._make_file_chunks(node))
                    if node.compress:
                        node.seg.FILE_ZSIZE = stored_size
                    bw.write_align(16)

                fs_end = bw.tell()
                bw.seek(fs_seg.FS_ABSOLUTE_OFS)
                bw.write_bytes(make_endiltle(tables["ENDILTLE"]))
                bw.write_bytes(make_packfshd(tables["PACKFSHD"]))
                bw.write_bytes(make_genestrt(tables["GENESTRT"]))
                bw.write_bytes(make_geneeof(tables["GENEEOF"]))
                bw.flush()

                fs_seg.FS_SIZE = fs_end - fs_seg.FS_ABSOLUTE_OFS
                md5 = hashlib.md5()
                with BinaryReader(self.TEMP_PATH) as br:
                    br.seek(fs_seg.FS_ABSOLUTE_OFS)
                    for chunk in br.read_chunks(fs_seg.FS_SIZE):
                        md5.update(chunk)
                fs_seg.FS_HASH = md5.digest()

                bw.seek(fs_end)
                if i != len(self.FS_NODES) - 1:
                    bw.write_align(2048 if self.FS_PAD_TYPE == 1 else 512)

            # write root tables
            bw.seek(0)
            bw.write_bytes(make_endiltle(self.ROOT_TABLES["ENDILTLE"]))
            bw.write_bytes(make_packhedr(self.ROOT_TABLES["PACKHEDR"]))
            bw.write_bytes(make_packtoc(self.ROOT_TABLES["PACKTOC"]))
            bw.write_bytes(make_packfsls(self.ROOT_TABLES["PACKFSLS"]))
            bw.write_bytes(make_genestrt(self.ROOT_TABLES["GENESTRT"]))
            bw.write_bytes(make_geneeof(self.ROOT_TABLES["GENEEOF"]))

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

    def _make_toc_seg_list(self) -> list[TOC_SEGMENT]:
        name_idx = self.ROOT_NAME_IDX

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

        root = PackNode(name="", is_dir=True, children=self.ROOT_NODES)
        seg_list: list[TOC_SEGMENT] = [make_seg(root)]

        def layout(seg: TOC_SEGMENT, nodes: list[PackNode]) -> None:
            seg.ENTRY_INDEX = len(seg_list) if nodes else 0
            seg.ENTRY_COUNT = len(nodes)

            children = [make_seg(node) for node in nodes]
            seg_list.extend(children)
            for child, node in zip(children, nodes):
                if node.is_dir:
                    layout(child, node.children)

        layout(seg_list[0], root.children)

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
        name_idx = self.ROOT_NAME_IDX

        return [FS_SEGMENT(
            NAME_IDX=name_idx[fs_name],
            PACKAGE_NAME_IDX=0,
            FS_ABSOLUTE_OFS=0,
            FS_SIZE=0,
            FS_HASH=b"\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0",
        ) for fs_name in self.FS_NODES]

    def _iter_paths(self, nodes: list[PackNode], prefix: str = "") -> Iterator[str]:
        for node in nodes:
            path = f"{prefix}{node.name}"
            if node.is_dir:
                yield from self._iter_paths(node.children, f"{path}/")
            else:
                yield path

    def _iter_files(self, nodes: list[PackNode]) -> Iterator[PackNode]:
        for node in nodes:
            if node.is_dir:
                yield from self._iter_files(node.children)
            else:
                yield node

    def _make_file_chunks(self, node: PackNode) -> Iterator[bytes]:
        assert node.src_path is not None
        with BinaryReader(node.src_path) as br:
            if node.compress:
                compressor = zlib.compressobj(9)
                for chunk in br.read_chunks(node.size):
                    yield compressor.compress(chunk)
                yield compressor.flush()
            else:
                yield from br.read_chunks(node.size)

    def _make_fs_file_seg_list(self, nodes: list[PackNode]) -> list[FS_FILE_SEG]:
        seg_list: list[FS_FILE_SEG] = []
        for i, node in enumerate(nodes):
            seg = FS_FILE_SEG(
                NAME_IDX=i,
                COMPRESS_TYPE=2 if node.compress else 0,
                unknown_1=0,
                unknown_2=0,
                unknown_3=0,
                FILE_OFS=0,
                FILE_SIZE=node.size,
                FILE_ZSIZE=0,
            )
            node.seg = seg
            seg_list.append(seg)
        return seg_list
