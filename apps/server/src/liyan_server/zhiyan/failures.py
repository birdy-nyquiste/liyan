"""Why one 知言 run produced no 知言报告.

Transport and acceptance fail for different reasons but carry the same three
things: a stable code, a message the user may read, and internal detail that must
never reach the browser. One base type lets a run handle both in one place.
"""


class ZhiyanRunFailure(Exception):
    def __init__(self, code: str, message: str, internal_error: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.internal_error = internal_error
