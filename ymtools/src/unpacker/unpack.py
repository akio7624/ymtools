import logging
import zlib
from pathlib import Path

from ymtools.src.binutils.BinaryReader import BinaryReader
from ymtools.src.structure.apk import APK
from ymtools.src.structure.utils import walk_toc


log = logging.getLogger(__name__)


class Unpacker:
    def __init__(self, input_path: Path, output_dir: Path, combine_fs: bool, worker_num: int) -> None:
        self.INPUT_PATH = input_path
        self.OUTPUT_DIR = output_dir
        self.COMBINE_FS = combine_fs
        self.WORKER_NUM = worker_num

    def run(self) -> int:
        apk = APK.read_apk(self.INPUT_PATH)

        br = BinaryReader(self.INPUT_PATH)
        string_list = apk.get_string_list()
        toc_seg_list = apk.get_toc_seg_list()
        file_sets = apk.get_file_sets()

        log.info(f"Segment count for extract: {len(toc_seg_list)}")

        package_dir = self.OUTPUT_DIR / apk.get_package_name()
        root_dir = package_dir if self.COMBINE_FS else package_dir / "ROOT"
        fs_dir = package_dir if self.COMBINE_FS else package_dir / "FS"

        paths, _ = walk_toc(toc_seg_list, string_list)
        progress: int = 0
        out_path: Path = root_dir
        try:
            # ====================== Root Files ======================
            for i, seg in enumerate(toc_seg_list):
                if progress % 50 == 0:
                    log.info(f"Processing toc segments...({progress}/{len(toc_seg_list)})")
                progress += 1

                path = paths[i]
                if path is None:
                    log.warning("Skip TOC_SEG_LIST[%d]: it is not reachable from the root", i)
                    continue

                if seg.IDENTIFIER == 1:  # dir
                    (root_dir / path).mkdir(parents=True, exist_ok=True)
                elif seg.IDENTIFIER == 0:  # file
                    out_path = root_dir / path
                    log.debug("Extract root file %s", out_path)
                    if not self._extract_file(br, out_path, seg.FILE_ABSOLUTE_OFS, seg.FILE_SIZE, seg.FILE_ZSIZE, seg.COMPRESS_TYPE):
                        return 1
            log.info(f"Processed {len(toc_seg_list)} toc segments")

            # ====================== File Sets ======================
            for i, fs in enumerate(file_sets):
                fs_name = string_list[fs.SEGMENT.NAME_IDX]
                fs_string_list = fs.FS_GENESTRT.STRING_LIST
                fs_file_seg_list = fs.FS_PACKFSHD.FS_FILE_SEG_LIST
                log.info(f"Processing FILE_SET[{i}] '{fs_name}' ({len(fs_file_seg_list)} files)")

                (fs_dir / fs_name).mkdir(parents=True, exist_ok=True)
                for file_seg in fs_file_seg_list:
                    out_path = fs_dir / fs_name / fs_string_list[file_seg.NAME_IDX]
                    log.debug("Extract FS file %s", out_path)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    if not self._extract_file(br, out_path, fs.SEGMENT.FS_ABSOLUTE_OFS + file_seg.FILE_OFS, file_seg.FILE_SIZE, file_seg.FILE_ZSIZE, file_seg.COMPRESS_TYPE):
                        return 1
            log.info(f"Processed {len(file_sets)} file sets")
        except (zlib.error, EOFError) as e:
            log.error("Failed to extract %s (%s: %s)", out_path, type(e).__name__, e)
            return 1
        finally:
            br.close()

        return 0

    def _extract_file(self, br: BinaryReader, out_path: Path, ofs: int, size: int, zsize: int, compress_type: int) -> bool:
        br.seek(ofs)
        written = 0
        with open(out_path, "wb") as f:
            if compress_type == 2:
                decompressor = zlib.decompressobj()
                for chunk in br.read_chunks(zsize):
                    written += f.write(decompressor.decompress(chunk))
                written += f.write(decompressor.flush())
            else:
                for chunk in br.read_chunks(size):
                    written += f.write(chunk)
        if written != size:
            log.error(f"Unexpected file size: {written} while extracting {out_path}")
            return False
        return True
