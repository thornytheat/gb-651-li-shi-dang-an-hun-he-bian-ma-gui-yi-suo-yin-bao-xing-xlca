from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(ValueError):
    """可安全返回给调用方的业务异常。

    ``status_code`` 让调用方区分「请求体不合法」(422)、
    「与已确认状态冲突」(409) 与「对象不存在」(404)。
    """

    def __init__(self, code: str, message: str, status_code: int = 422, **details):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)

    def as_dict(self) -> dict:
        body = {"error": self.code, "reason": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return body


def install(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content=exc.as_dict())
