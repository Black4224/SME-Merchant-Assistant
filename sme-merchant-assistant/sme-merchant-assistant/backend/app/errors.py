"""Application errors -> uniform JSON: {"error": {"code", "message", "details"?}}"""


class AppError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str, *, details=None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Unprocessable(AppError):
    status_code = 422
    code = "unprocessable"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class ServiceUnavailable(AppError):
    status_code = 503
    code = "service_unavailable"


class BadGateway(AppError):
    status_code = 502
    code = "bad_gateway"
