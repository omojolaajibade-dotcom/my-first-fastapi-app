
import os
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OMOTECH_SKIP_CREATE_ALL"] = "1"

import main


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSession = sessionmaker(bind=engine)

main.Base.metadata.create_all(
    bind=engine,
    tables=[
        main.User.__table__,
        main.WalletTransaction.__table__,
    ],
)

main.SessionLocal = TestSession


def reset_db():
    main.Base.metadata.drop_all(
        bind=engine,
        tables=[
            main.WalletTransaction.__table__,
            main.User.__table__,
        ],
    )
    main.Base.metadata.create_all(
        bind=engine,
        tables=[
            main.User.__table__,
            main.WalletTransaction.__table__,
        ],
    )


def create_user(balance="1000.00"):
    db = TestSession()
    create_user.counter = getattr(create_user, "counter", 0) + 1

    user = main.User(
        name="Ridamsub Data Test",
        phone=f"0804000{create_user.counter:04d}",
        wallet_balance=Decimal(balance),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    user_id = user.id
    db.close()
    return user_id


def wallet_balance(user_id):
    db = TestSession()
    user = db.query(main.User).filter_by(id=user_id).first()
    result = Decimal(str(user.wallet_balance))
    db.close()
    return result


def get_transaction(reference):
    db = TestSession()
    tx = (
        db.query(main.WalletTransaction)
        .filter_by(reference=reference)
        .first()
    )
    if tx is None:
        db.close()
        return None

    result = {
        "status": tx.status,
        "amount": Decimal(str(tx.amount)),
        "wallet_debited": tx.wallet_debited,
        "gateway": tx.gateway,
        "transaction_type": tx.transaction_type,
    }
    db.close()
    return result


def fake_client(response=None, error=None):
    client = Mock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    if error:
        client.post = AsyncMock(side_effect=error)
    else:
        client.post = AsyncMock(return_value=response)

    return client


def fake_response():
    response = Mock()
    response.status_code = 200
    response.text = '{"Status": "mock response"}'
    response.json.return_value = {
        "Status": "mock response",
        "id": "MOCK-RIDAM-DATA-001",
    }
    return response


def run_purchase(
    user_id,
    key,
    client,
    normalized_status=None,
):
    patches = [
        patch.object(main, "RIDAMSUB_PURCHASES_ENABLED", True),
        patch.object(
            main,
            "ridamsub_headers",
            return_value={"Authorization": "Token mock"},
        ),
        patch.object(
            main,
            "RIDAMSUB_DATA_PLANS",
            {
                "mtn": [
                    {
                        "plan_id": 6,
                        "provider_cost": Decimal("170.00"),
                        "available": True,
                    }
                ]
            },
        ),
        patch.object(
            main,
            "resolve_purchase_amount",
            return_value=Decimal("300.00"),
        ),
        patch.object(main.httpx, "AsyncClient", return_value=client),
    ]

    if normalized_status is not None:
        patches.append(
            patch.object(
                main,
                "normalize_provider_status",
                return_value=normalized_status,
            )
        )

    db = TestSession()

    try:
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            if len(patches) == 6:
                with patches[5]:
                    return asyncio.run(
                        main.execute_ridamsub_purchase(
                            db=db,
                            user_id=user_id,
                            purchase_type="data",
                            network="mtn",
                            phone="08012345678",
                            idempotency_key=key,
                            plan_id=6,
                        )
                    )

            return asyncio.run(
                main.execute_ridamsub_purchase(
                    db=db,
                    user_id=user_id,
                    purchase_type="data",
                    network="mtn",
                    phone="08012345678",
                    idempotency_key=key,
                    plan_id=6,
                )
            )
    finally:
        db.close()


def test_success_debits_once():
    reset_db()
    uid = create_user()
    client = fake_client(response=fake_response())

    result = run_purchase(
        uid, "ridam-data-success", client, "success"
    )

    tx = get_transaction(result["reference"])

    assert result["status"] == "success"
    assert wallet_balance(uid) == Decimal("700.00")
    assert tx["wallet_debited"] is True
    assert tx["gateway"] == "ridamsub"
    assert tx["transaction_type"] == "data_purchase"
    assert client.post.await_count == 1

    print("PASS: Ridamsub data success debits exactly once.")


def test_failure_does_not_debit():
    reset_db()
    uid = create_user()
    client = fake_client(response=fake_response())

    result = run_purchase(
        uid, "ridam-data-failure", client, "failed"
    )

    tx = get_transaction(result["reference"])

    assert result["status"] == "failed"
    assert wallet_balance(uid) == Decimal("1000.00")
    assert tx["wallet_debited"] is False
    assert client.post.await_count == 1

    print("PASS: Ridamsub data failure causes no debit.")


def test_timeout_stays_pending_without_debit():
    reset_db()
    uid = create_user()

    client = fake_client(
        error=httpx.TimeoutException("Simulated timeout")
    )

    result = run_purchase(
        uid, "ridam-data-timeout", client
    )

    tx = get_transaction(result["reference"])

    assert result["status"] == main.PENDING_REQUERY
    assert tx["status"] == main.PENDING_REQUERY
    assert wallet_balance(uid) == Decimal("1000.00")
    assert tx["wallet_debited"] is False
    assert client.post.await_count == 1

    print("PASS: Timeout stays pending, with no debit or retry.")


def test_duplicate_request_does_not_submit_twice():
    reset_db()
    uid = create_user()
    client = fake_client(response=fake_response())

    first = run_purchase(
        uid, "ridam-data-duplicate", client, "success"
    )

    second = run_purchase(
        uid, "ridam-data-duplicate", client, "success"
    )

    assert first["reference"] == second["reference"]
    assert wallet_balance(uid) == Decimal("700.00")
    assert client.post.await_count == 1

    print("PASS: Duplicate request does not debit or submit twice.")


def test_insufficient_balance_stops_before_provider():
    reset_db()
    uid = create_user("100.00")
    client = fake_client(response=fake_response())

    try:
        run_purchase(
            uid, "ridam-data-insufficient", client, "success"
        )
        raise AssertionError("Expected insufficient balance rejection.")

    except HTTPException as exc:
        assert exc.status_code == 400

    assert wallet_balance(uid) == Decimal("100.00")
    assert client.post.await_count == 0

    db = TestSession()
    count = (
        db.query(main.WalletTransaction)
        .filter_by(user_id=uid)
        .count()
    )
    db.close()

    assert count == 0

    print("PASS: Insufficient balance stops before transaction/provider call.")


if __name__ == "__main__":
    try:
        test_success_debits_once()
        test_failure_does_not_debit()
        test_timeout_stays_pending_without_debit()
        test_duplicate_request_does_not_submit_twice()
        test_insufficient_balance_stops_before_provider()

        print("\nALL RIDAMSUB DATA WALLET TESTS PASSED.")

    finally:
        engine.dispose()
