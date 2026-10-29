"""Defence in depth: while a tool runs, ANY non-SELECT SQL statement raises.
Tools are read-only by design; this makes it impossible even by accident."""
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event
from sqlalchemy.engine import Engine

_read_only: ContextVar[bool] = ContextVar("tool_read_only", default=False)


class ReadOnlyViolation(RuntimeError):
    pass


@event.listens_for(Engine, "before_cursor_execute")
def _guard(conn, cursor, statement, parameters, context, executemany):
    if _read_only.get():
        head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
        if head not in ("SELECT", "WITH", "PRAGMA"):
            raise ReadOnlyViolation(f"write attempted inside a read-only tool: {head}")


@contextmanager
def read_only():
    token = _read_only.set(True)
    try:
        yield
    finally:
        _read_only.reset(token)
