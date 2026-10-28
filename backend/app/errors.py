class APIError(Exception):
    """An intentionally public error; never include SQL or source exception text."""

    def __init__(self, status_code: int, code: str, message: str, fields: list[str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields or []
