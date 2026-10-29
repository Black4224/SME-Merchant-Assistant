from math import ceil

from fastapi import Query

from app.services.transaction_queries import MAX_PAGE_SIZE


def page_params(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE)):
    return page, page_size


def paginate(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, ceil(total / page_size)) if total else 0}
