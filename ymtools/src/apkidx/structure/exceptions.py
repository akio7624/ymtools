__all__ = ["ValidationException", "ApkException", "IdxException"]


class ValidationException(Exception):
    LABEL = ""

    def __init__(self, violations: list[str]) -> None:
        super().__init__(f"{self.LABEL} validation failed: {len(violations)} violation(s)")
        self.violations = violations


class ApkException(ValidationException):
    LABEL = "APK"


class IdxException(ValidationException):
    LABEL = "IDX"
