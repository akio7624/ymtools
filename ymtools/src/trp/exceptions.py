from ymtools.src.apkidx.structure.exceptions import ValidationException

__all__ = ["TrpException", "TrpUnpackException", "TrpPackException"]


class TrpException(ValidationException):
    LABEL = "TRP"


class TrpUnpackException(Exception):
    pass


class TrpPackException(Exception):
    pass
