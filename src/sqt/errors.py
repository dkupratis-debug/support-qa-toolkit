"""User-facing errors. The CLI prints these and exits; it does not traceback."""


class SqtError(Exception):
    """A problem in the input or the invocation, explained for a human."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code
