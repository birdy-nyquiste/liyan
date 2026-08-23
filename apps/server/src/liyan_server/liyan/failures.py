class LiyanRunFailure(Exception):
    def __init__(self, code: str, message: str, internal_error: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.internal_error = internal_error
