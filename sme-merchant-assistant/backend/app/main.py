"""FastAPI entry point.  Run from backend/:  uvicorn app.main:app --reload"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import assistant, customers, imports, reports, system, transactions
from app.config import get_settings
from app.database import init_db
from app.errors import AppError
from app.services.money import InvalidAmount
from app.services.periods import InvalidDateRange
from app.services.transactions import BusinessRuleError

log = logging.getLogger("sme")


def _error(status: int, code: str, message: str, details=None) -> JSONResponse:
    body = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="SME & Merchant Assistant API", version=system.VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return _error(e.status_code, e.code, e.message, e.details)

    @app.exception_handler(BusinessRuleError)
    async def _rule(_: Request, e: BusinessRuleError):
        return _error(422, "business_rule", str(e))

    @app.exception_handler(InvalidAmount)
    async def _amount(_: Request, e: InvalidAmount):
        return _error(422, "invalid_amount", str(e))

    @app.exception_handler(InvalidDateRange)
    async def _range(_: Request, e: InvalidDateRange):
        return _error(422, "invalid_date_range", str(e))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]),
                    "message": str(err["msg"]).removeprefix("Value error, ")} for err in e.errors()]
        return _error(422, "validation_error", "بيانات الطلب غير صالحة", details)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception):
        log.exception("unhandled error")
        return _error(500, "internal_error", "حدث خطأ غير متوقع")

    for r in (system.router, transactions.router, customers.router, imports.router, reports.router, assistant.router):
        app.include_router(r)
    return app


app = create_app()
