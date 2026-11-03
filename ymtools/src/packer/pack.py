import logging
from pathlib import Path

log = logging.getLogger(__name__)


class Packer:
    def __init__(self, input_dir: Path, output_path: Path) -> None:
        self.INPUT_DIR = input_dir
        self.OUTPUT_PATH = output_path

    def run(self) -> int:
        # TODO ...

        return 0
