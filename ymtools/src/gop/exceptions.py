from ymtools.src.structure.exceptions import ValidationException

__all__ = ["GopException", "GopDumpException"]


class GopException(ValidationException):
    LABEL = "GOP"


class GopDumpException(Exception):
    pass
