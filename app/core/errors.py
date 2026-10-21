"""Safe public errors; exceptions never expose provider or database messages."""


class AppError(Exception):
    def __init__(self, code: str, status_code: int = 400):
        self.code = code
        self.status_code = status_code
