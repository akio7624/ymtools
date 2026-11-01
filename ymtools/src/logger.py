import logging
import logging.handlers
import multiprocessing
from pathlib import Path
from queue import Queue
from typing import override

from rich.console import Console
from rich.logging import RichHandler
from rich.style import Style
from rich.text import Text
from rich.theme import Theme

LEVEL_STYLES = {
    logging.DEBUG: Style(dim=True),
    logging.INFO: Style(color="green"),
    logging.WARNING: Style(color="yellow"),
    logging.ERROR: Style(color="red"),
    logging.CRITICAL: Style(color="red", bold=True, reverse=True),
}

THEME = Theme({"log.time": Style(color="magenta")})
TIME_FORMAT = "%H:%M:%S"
FILE_FORMAT = "%(asctime)s [%(levelname).1s] %(processName)s %(name)s: %(message)s"


class ColorHandler(RichHandler):
    @override
    def get_level_text(self, record: logging.LogRecord) -> Text:
        return Text(f"[{record.levelname[0]}]", style=LEVEL_STYLES.get(record.levelno, Style()))

    @override
    def render_message(self, record: logging.LogRecord, message: str) -> Text:
        text = Text(message)  # no markup parsing
        text.stylize(LEVEL_STYLES.get(record.levelno, Style()))
        return text


def _build_handlers(log_file: Path) -> list[logging.Handler]:
    console = ColorHandler(console=Console(theme=THEME), show_path=False, rich_tracebacks=True, markup=False)
    console.setFormatter(logging.Formatter("%(message)s", datefmt=TIME_FORMAT))

    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=TIME_FORMAT))
    return [console, fh]


def setup_cli_logging(level: int | None, log_file: Path) -> tuple[logging.handlers.QueueListener, Queue]:
    queue = multiprocessing.Manager().Queue(-1)
    handlers = [] if level is None else _build_handlers(log_file)
    listener = logging.handlers.QueueListener(queue, *handlers)
    listener.start()

    setup_worker_logging(queue, logging.CRITICAL + 1 if level is None else level)
    return listener, queue


def setup_worker_logging(queue: Queue, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(logging.handlers.QueueHandler(queue))
