"""Errors raised by the VassilFlow Office engine."""


class OfficeError(Exception):
    """Base error for deterministic Office operations."""


class OfficePathError(OfficeError):
    """The requested virtual path violates the Office path policy."""


class OfficePackageError(OfficeError):
    """The input is not a supported or safe Office package."""


class OfficeOperationError(OfficeError):
    """An Office edit could not be applied without risking document damage."""


class OfficeRevisionError(OfficeError):
    """An Office project revision could not be persisted safely."""


class OfficeRevisionConflictError(OfficeRevisionError):
    """An Office project advanced beyond the caller's expected parent revision."""


class OfficeRevisionIntegrityError(OfficeRevisionError):
    """Persisted Office project metadata or artifact bytes failed integrity checks."""


class OfficeTemplateError(OfficeError):
    """An Office template could not be imported, mapped, or published safely."""


class OfficeTemplateConflictError(OfficeTemplateError):
    """An Office template changed beyond the caller's expected draft state."""


class OfficeTemplateIntegrityError(OfficeTemplateError):
    """Persisted Office template metadata or source bytes failed integrity checks."""


class OfficeRenderError(OfficeError):
    """An Office document could not be rendered within the supported contract."""


class OfficeRenderUnavailableError(OfficeRenderError):
    """The isolated Office renderer service is not reachable or configured."""


class UnsupportedOfficeFormatError(OfficeError):
    """The requested Office format is not implemented yet."""
