from pathlib import Path

from ymtools.src.structure.apk import APK


class Unpacker:
    def __init__(self, input_path: Path, output_dir: Path, combine_fs: bool, worker_num: int) -> None:
        self.INPUT_PATH = input_path
        self.OUTPUT_DIR = output_dir
        self.COMBINE_FS = combine_fs
        self.WORKER_NUM = worker_num

    def run(self) -> int:
        apk = APK.read_apk(self.INPUT_PATH)
        # TODO ...

        return 0
