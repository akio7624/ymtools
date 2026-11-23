from ymtools.src.apkidx.structure.exceptions import ValidationException

__all__ = ["GopException", "GopDumpException", "GopPatchException"]


class GopException(ValidationException):
    LABEL = "GOP"


class GopDumpException(Exception):
    pass


class GopPatchException(ValidationException):
    LABEL = "GOP patch"
