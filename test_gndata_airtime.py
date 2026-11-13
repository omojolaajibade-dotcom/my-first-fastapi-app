import os
import asyncio
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OMOTECH_SKIP_CREATE_ALL"] = "1"
os.environ["GNDATA_ENABLED"] = "true"
os.environ["GNDATA_API_KEY"] = "mock-only-test-credential"

import main


class FakeGNClient:
    enabled = True
    api_key = "mock-only-test-credential"

    def __init__(self, outcome="success"):
        self.outcome = outcome
        self.calls = 0
        self.last_kwargs = None

    async def purchase_airtime(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs

        if self.outcome == "timeout":
            raise main.GNDataError("Simulated GN airtime timeout")

        if self.outcome == "failed":
            return {
                "status": "failed",
                "request_id": "MOCK-AIRTIME-FAIL",
            }

        return {
            "status": "success",
            "request_id": "MOCK-AIRTIME-001",
        }


def setup_case(name, balance="1000.00"):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )

    TestSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    main.Base.metadata.create_all(
        bind=engine,
        tables=[
            main.User.__table__,
            main.WalletTransaction.__table__,
        ],
    )

    db = TestSession()
    user = main.User(
        name=name,
        phone="08030000001",
        wallet_balance=Decimal(balance),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return engine, TestSession, db, user


def run_purchase(db, user, client, key):
    with patch.object(
        main,
        "GNDataClient",
        return_value=client,
    ), patch.object(
        main,
        "SessionLocal",
        db.get_bind_sessionmaker if hasattr(db, "get_bind_sessionmaker") else TestSessionFor(db),
    ):
        return asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key=key,
            )
        )


def TestSessionFor(db):
    return sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        autocommit=False,
    )


# TEST 1: Successful GN airtime purchase

print("\n--- TEST 1: Successful GN airtime purchase ---")

engine, Session, db, user = setup_case(
    "GN Airtime Success Customer"
)
client = FakeGNClient("success")

try:
    with patch.object(
        main, "GNDataClient", return_value=client
    ), patch.object(
        main, "SessionLocal", Session
    ):
        result = asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key="gn-airtime-success-001",
            )
        )

    db.refresh(user)

    transaction = db.query(
        main.WalletTransaction
    ).filter_by(
        user_id=user.id,
        idempotency_key="gn-airtime-success-001",
    ).first()

    print("Result:", result)
    print("Wallet:", user.wallet_balance)
    print("Transaction status:", transaction.status)
    print("Provider calls:", client.calls)
    print("Provider request:", client.last_kwargs)

    assert result["status"] == "success"
    assert user.wallet_balance == Decimal("900.00")
    assert transaction is not None
    assert transaction.status == "success"
    assert transaction.gateway == "gndata"
    assert transaction.provider_cost is None
    assert client.calls == 1
    assert client.last_kwargs["network_id"] == 14
    assert client.last_kwargs["amount"] == 100
    assert client.last_kwargs["phone"] == "08030000001"

    print("PASS: GN airtime success and correct wallet debit.")

finally:
    db.close()
    engine.dispose()


# TEST 2: Duplicate request must not debit or call provider again

print("\n--- TEST 2: Duplicate airtime request ---")

engine, Session, db, user = setup_case(
    "GN Airtime Duplicate Customer"
)
client = FakeGNClient("success")

try:
    with patch.object(
        main, "GNDataClient", return_value=client
    ), patch.object(
        main, "SessionLocal", Session
    ):
        first = asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key="gn-airtime-duplicate-001",
            )
        )

        second = asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key="gn-airtime-duplicate-001",
            )
        )

    db.refresh(user)

    count = db.query(
        main.WalletTransaction
    ).filter_by(user_id=user.id).count()

    print("First:", first)
    print("Second:", second)
    print("Wallet:", user.wallet_balance)
    print("Transactions:", count)
    print("Provider calls:", client.calls)

    assert user.wallet_balance == Decimal("900.00")
    assert count == 1
    assert client.calls == 1
    assert first["reference"] == second["reference"]

    print("PASS: Duplicate request caused no second debit or provider call.")

finally:
    db.close()
    engine.dispose()


# TEST 3: Insufficient balance must not call GN

print("\n--- TEST 3: Insufficient wallet balance ---")

engine, Session, db, user = setup_case(
    "GN Airtime Insufficient Customer",
    balance="50.00",
)
client = FakeGNClient("success")

try:
    with patch.object(
        main, "GNDataClient", return_value=client
    ), patch.object(
        main, "SessionLocal", Session
    ):
        try:
            asyncio.run(
                main.execute_gndata_airtime_purchase(
                    db=db,
                    user_id=user.id,
                    network="mtn",
                    phone="08030000001",
                    amount=100,
                    idempotency_key="gn-airtime-insufficient-001",
                )
            )
            raise AssertionError("Expected HTTP 400.")

        except HTTPException as exc:
            assert exc.status_code == 400
            print("Rejected with HTTP 400.")

    db.refresh(user)

    count = db.query(
        main.WalletTransaction
    ).filter_by(user_id=user.id).count()

    print("Wallet:", user.wallet_balance)
    print("Transactions:", count)
    print("Provider calls:", client.calls)

    assert user.wallet_balance == Decimal("50.00")
    assert count == 0
    assert client.calls == 0

    print("PASS: Insufficient balance caused no debit or provider call.")

finally:
    db.close()
    engine.dispose()


# TEST 4: Uncertain GN response must remain pending

print("\n--- TEST 4: GN airtime timeout ---")

engine, Session, db, user = setup_case(
    "GN Airtime Timeout Customer"
)
client = FakeGNClient("timeout")

try:
    with patch.object(
        main, "GNDataClient", return_value=client
    ), patch.object(
        main, "SessionLocal", Session
    ):
        result = asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key="gn-airtime-timeout-001",
            )
        )

    db.refresh(user)

    transaction = db.query(
        main.WalletTransaction
    ).filter_by(
        user_id=user.id,
        idempotency_key="gn-airtime-timeout-001",
    ).first()

    print("Result:", result)
    print("Wallet:", user.wallet_balance)
    print("Transaction status:", transaction.status)
    print("Provider calls:", client.calls)

    assert result["status"] == main.PENDING_REQUERY
    assert transaction is not None
    assert transaction.status == main.PENDING_REQUERY
    assert transaction.gateway == "gndata"
    assert user.wallet_balance == Decimal("900.00")
    assert client.calls == 1
    assert transaction.provider_transaction_id is None

    print("PASS: Timeout remains pending; no automatic refund or retry.")

finally:
    db.close()
    engine.dispose()


# TEST 5: Definitive provider failure refunds exactly once

print("\n--- TEST 5: GN airtime failure and refund ---")

engine, Session, db, user = setup_case(
    "GN Airtime Refund Customer"
)
client = FakeGNClient("failed")

try:
    with patch.object(
        main, "GNDataClient", return_value=client
    ), patch.object(
        main, "SessionLocal", Session
    ):
        result = asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key="gn-airtime-failed-001",
            )
        )

    db.refresh(user)

    transaction = db.query(
        main.WalletTransaction
    ).filter_by(
        user_id=user.id,
        idempotency_key="gn-airtime-failed-001",
    ).first()

    print("Result:", result)
    print("Wallet after failure:", user.wallet_balance)
    print("Transaction status:", transaction.status)

    assert transaction.status == "failed"
    assert user.wallet_balance == Decimal("1000.00")
    assert client.calls == 1

    with patch.object(main, "SessionLocal", Session):
        main.apply_provider_result(
            transaction.reference,
            "failed",
            gateway="gndata",
        )

    db.expire_all()
    user = db.query(main.User).filter_by(id=user.id).first()

    assert user.wallet_balance == Decimal("1000.00")

    print("PASS: Definitive failure refunded exactly once.")

finally:
    db.close()
    engine.dispose()


# TEST 6 and 7: GN definitive rejection -> Ridamsub fallback

class DefinitiveRejectGNClient:
    enabled = True
    api_key = "mock-only-test-credential"

    def __init__(self):
        self.calls = 0

    async def purchase_airtime(self, **kwargs):
        self.calls += 1
        raise main.GNDataError(
            "GN airtime endpoint rejected",
            status_code=404,
            response_body="Route not found",
        )


class FakeRidamsubResponse:
    status_code = 200

    def json(self):
        return {
            "status": "success",
            "ident": "MOCK-RIDAMSUB-AIRTIME-001",
        }


class FakeRidamsubAsyncClient:
    outcome = "success"
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).calls.append({
            "url": url,
            "headers": headers,
            "payload": json,
        })

        if type(self).outcome == "timeout":
            raise RuntimeError("Simulated Ridamsub timeout")

        return FakeRidamsubResponse()


# TEST 6: Definitive GN rejection; Ridamsub succeeds

print("\n--- TEST 6: GN rejection followed by Ridamsub success ---")

engine, Session, db, user = setup_case(
    "GN Airtime Ridamsub Fallback Customer"
)
gn_client = DefinitiveRejectGNClient()
FakeRidamsubAsyncClient.outcome = "success"
FakeRidamsubAsyncClient.calls = []

try:
    with (
        patch.object(main, "GNDataClient", return_value=gn_client),
        patch.object(main, "SessionLocal", Session),
        patch.object(
            main, "ridamsub_headers",
            return_value={"Authorization": "Token mock-only"},
        ),
        patch.object(
            main.httpx,
            "AsyncClient",
            FakeRidamsubAsyncClient,
        ),
    ):
        result = asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key="gn-airtime-fallback-success-001",
            )
        )

    db.refresh(user)

    transactions = db.query(
        main.WalletTransaction
    ).filter_by(user_id=user.id).all()

    transaction = transactions[0]
    ridamsub_request = FakeRidamsubAsyncClient.calls[0]

    print("Result:", result)
    print("Wallet:", user.wallet_balance)
    print("Gateway:", transaction.gateway)
    print("Transaction count:", len(transactions))
    print("Ridamsub calls:", len(FakeRidamsubAsyncClient.calls))

    assert gn_client.calls == 1
    assert len(FakeRidamsubAsyncClient.calls) == 1
    assert len(transactions) == 1
    assert transaction.gateway == "ridamsub"
    assert transaction.status == "success"
    assert transaction.provider_transaction_id == "MOCK-RIDAMSUB-AIRTIME-001"
    assert ridamsub_request["payload"]["request-id"] == transaction.reference
    assert user.wallet_balance == Decimal("900.00")
    assert transaction.provider_cost == Decimal("98.00")

    print("PASS: Same transaction reused; one debit; Ridamsub success.")

finally:
    db.close()
    engine.dispose()


# TEST 7: Ridamsub timeout after definitive GN rejection

print("\n--- TEST 7: Ridamsub fallback timeout ---")

engine, Session, db, user = setup_case(
    "GN Airtime Ridamsub Timeout Customer"
)
gn_client = DefinitiveRejectGNClient()
FakeRidamsubAsyncClient.outcome = "timeout"
FakeRidamsubAsyncClient.calls = []

try:
    with (
        patch.object(main, "GNDataClient", return_value=gn_client),
        patch.object(main, "SessionLocal", Session),
        patch.object(
            main, "ridamsub_headers",
            return_value={"Authorization": "Token mock-only"},
        ),
        patch.object(
            main.httpx,
            "AsyncClient",
            FakeRidamsubAsyncClient,
        ),
    ):
        result = asyncio.run(
            main.execute_gndata_airtime_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                amount=100,
                idempotency_key="gn-airtime-fallback-timeout-001",
            )
        )

    db.refresh(user)

    transactions = db.query(
        main.WalletTransaction
    ).filter_by(user_id=user.id).all()

    transaction = transactions[0]

    print("Result:", result)
    print("Wallet:", user.wallet_balance)
    print("Gateway:", transaction.gateway)
    print("Transaction status:", transaction.status)
    print("Transaction count:", len(transactions))
    print("Ridamsub calls:", len(FakeRidamsubAsyncClient.calls))

    assert gn_client.calls == 1
    assert len(FakeRidamsubAsyncClient.calls) == 1
    assert len(transactions) == 1
    assert transaction.gateway == "ridamsub"
    assert transaction.status == main.PENDING_REQUERY
    assert result["status"] == main.PENDING_REQUERY
    assert user.wallet_balance == Decimal("900.00")

    print("PASS: Timeout remains pending; no second debit or refund.")

finally:
    db.close()
    engine.dispose()


print("\nALL GN AIRTIME SAFETY TESTS PASSED.")
