"""Only transport errors and explicitly transient provider codes are retryable."""
from google.genai.errors import APIError
from websockets.exceptions import ConnectionClosed


def transient(exc: Exception) -> bool:
    if isinstance(exc, APIError):
        return exc.code in {408, 429, 500, 502, 503, 504, 1000, 1001, 1006, 1011, 1012, 1013}
    return isinstance(exc, (ConnectionClosed, ConnectionError, TimeoutError, OSError))
