import re
from abc import ABC, abstractmethod

from vassilflow.sandbox.search import GrepMatch

# POSIX env-var name rule: letter or underscore, then letters/digits/underscores.
# Used to validate ``env`` keys before they reach a sandbox implementation.
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_extra_env(extra_env: dict[str, str] | None) -> None:
    """Reject ``env`` keys that are not valid POSIX env-var names."""
    if not extra_env:
        return
    for key in extra_env:
        if not isinstance(key, str) or not _ENV_NAME_PATTERN.fullmatch(key):
            raise ValueError(
                f"extra_env key {key!r} is not a valid POSIX environment variable name "
                "(must match ^[A-Za-z_][A-Za-z0-9_]*$)."
            )


class Sandbox(ABC):
    """Abstract base class for sandbox environments"""

    _id: str

    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    @abstractmethod
    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Execute bash command in sandbox.

        Args:
            command: The command to execute.
            env: Optional per-call environment variables to inject into the
                command process. Keys must be valid POSIX environment-variable
                names (``^[A-Za-z_][A-Za-z0-9_]*$``).
            timeout: Optional per-call wall-clock timeout in seconds. Sandboxes
                may ignore it when their backend does not expose a separate
                command timeout.

        Returns:
            The standard or error output of the command.

        Raises:
            ValueError: when an ``env`` key is not a valid env-var name.
        """
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read the content of a file.

        Args:
            path: The absolute path of the file to read.

        Returns:
            The content of the file.
        """
        pass

    @abstractmethod
    def download_file(self, path: str) -> bytes:
        """Download the binary content of a file.

        Args:
            path: The absolute path of the file to download.

        Returns:
            Raw file bytes.

        Raises:
            PermissionError: If path traversal is detected or the path is outside
                the allowed virtual prefix.
            OSError: If the file cannot be read or does not exist.  Both local
                and remote implementations must raise ``OSError`` so callers
                have a single exception type to handle.
        """
        pass

    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """List the contents of a directory.

        Args:
            path: The absolute path of the directory to list.
            max_depth: The maximum depth to traverse. Default is 2.

        Returns:
            The contents of the directory.
        """
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write content to a file.

        Args:
            path: The absolute path of the file to write to.
            content: The text content to write to the file.
            append: Whether to append the content to the file. If False, the file will be created or overwritten.
        """
        pass

    @abstractmethod
    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        """Find paths that match a glob pattern under a root directory."""
        pass

    @abstractmethod
    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        """Search for matches inside text files under a directory."""
        pass

    @abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        """Update a file with binary content.

        Args:
            path: The absolute path of the file to update.
            content: The binary content to write to the file.
        """
        pass
