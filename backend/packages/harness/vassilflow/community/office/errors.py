"""Errors raised by the VassilFlow Office engine."""


class OfficeError(Exception):
    """Base error for deterministic Office operations."""


class OfficePathError(OfficeError):
    """The requested virtual path violates the Office path policy."""


class OfficePackageError(OfficeError):
    """The input is not a supported or safe Office package."""


class OfficeOperationError(OfficeError):
    """An Office edit could not be applied without risking document damage."""


class OfficeRenderError(OfficeError):
    """An Office document could not be rendered within the supported contract."""


class OfficeRenderUnavailableError(OfficeRenderError):
    """The isolated Office renderer service is not reachable or configured."""


class UnsupportedOfficeFormatError(OfficeError):
    """The requested Office format is not implemented yet."""
