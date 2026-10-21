from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Customer, PaymentMethod, ReconciliationStatus, Supplier
from app.models import TransactionType as TT
from app.services.settings_service import set_setting
from app.services.transactions import add_transaction

D = date  # short alias used in tests
REF = date(2026, 10, 15)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        set_setting(s, "reference_date", REF.isoformat())
        yield s


@pytest.fixture
def parties(session):
    c1, c2 = Customer(name="زبون أ"), Customer(name="زبون ب")
    s1 = Supplier(name="مورد أ")
    session.add_all([c1, c2, s1])
    session.flush()
    return c1, c2, s1


@pytest.fixture
def txn(session):
    """Factory: txn(date, type, amount, method, **kw) with sensible defaults."""

    def make(d, ttype, amount, method="cash", *, desc=None, status="reconciled", **kw):
        return add_transaction(
            session,
            txn_date=d,
            type=TT(ttype),
            amount=amount,
            description=desc or f"{ttype} {d} {amount}",
            payment_method=PaymentMethod(method),
            status=ReconciliationStatus(status),
            **kw,
        )

    return make


@pytest.fixture(scope="session")
def _seed_template():
    """Seed once per test run; each test gets a fast byte-level clone of this database."""
    from scripts.seed_demo import seed_database

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng, expire_on_commit=False)() as s:
        seed_database(s)
    return eng


def _clone(template, target):
    src = template.raw_connection().driver_connection
    dst = target.raw_connection().driver_connection
    src.backup(dst)


@pytest.fixture
def seeded(session, _seed_template):
    """Full synthetic dataset in a throw-away in-memory DB."""
    session.close()
    _clone(_seed_template, session.get_bind())
    return session


# ------------------------------------------------------------------ API fixtures
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session as _Session  # noqa: E402


@pytest.fixture
def api_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _make_client(engine, raise_exceptions=True):
    from app.database import get_session
    from app.main import app

    def override():
        with _Session(engine, expire_on_commit=False) as s:
            yield s

    app.dependency_overrides[get_session] = override
    return TestClient(app, raise_server_exceptions=raise_exceptions)


@pytest.fixture
def client(api_engine):
    """Empty database."""
    c = _make_client(api_engine)
    yield c
    from app.main import app

    app.dependency_overrides.clear()


@pytest.fixture
def seeded_client(api_engine, _seed_template):
    _clone(_seed_template, api_engine)
    c = _make_client(api_engine)
    yield c
    from app.main import app

    app.dependency_overrides.clear()


@pytest.fixture
def engine_session(api_engine):
    with _Session(api_engine, expire_on_commit=False) as s:
        yield s
