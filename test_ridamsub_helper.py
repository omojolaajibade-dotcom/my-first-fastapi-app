
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from dotenv import load_dotenv
load_dotenv()

import main
from security import decrypt_phone_number


def make_fake_db():
    db = Mock()

    user = SimpleNamespace(
        id=3,
        wallet_balance=Decimal("1000.00"),
    )

    def make_query(first_result):
        query = Mock()
        query.filter.return_value = query
        query.with_for_update.return_value = query
        query.order_by.return_value = query
        query.first.return_value = first_result
        return query

    db.query.side_effect = [
        make_query(user),
        make_query(None),
    ]

    db.add.side_effect = lambda transaction: setattr(
        db, "saved_transaction", transaction
    )
    db.refresh.side_effect = lambda transaction: None

    return db


def make_async_client(response=None, error=None):
    client = Mock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    if error is not None:
        client.post = AsyncMock(side_effect=error)
    else:
        client.post = AsyncMock(return_value=response)

    return client


def mock_apply_provider_result(db):
    def apply_result(reference, provider_status, gateway="ridamsub"):
        transaction = db.saved_transaction

        assert transaction.reference == reference
        assert gateway == "ridamsub"

        transaction.status = (
            "success"
            if provider_status == "success"
            else main.PENDING_REQUERY
        )

        return {"status": transaction.status}

    return apply_result


def test_success():
    db = make_fake_db()

    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.text = '{"Status": "successful"}'
    fake_response.json.return_value = {
        "Status": "successful",
        "id": "MOCK-RIDAM-001",
    }

    client = make_async_client(response=fake_response)

    with (
        patch.object(main, "RIDAMSUB_PURCHASES_ENABLED", True),
        patch.object(main, "ridamsub_headers", return_value={"Authorization": "Token mock"}),
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
        patch.object(
            main,
            "apply_provider_result",
            side_effect=mock_apply_provider_result(db),
        ),
    ):
        result = asyncio.run(
            main.execute_ridamsub_purchase(
                db=db,
                user_id=3,
                purchase_type="data",
                network="mtn",
                phone="08012345678",
                idempotency_key="ridam-data-success-001",
                plan_id=6,
            )
        )

    transaction = db.saved_transaction

    assert result["status"] == "success"
    assert transaction.status == "success"
    assert transaction.reference == result["reference"]
    assert transaction.provider_transaction_id == "MOCK-RIDAM-001"
    assert transaction.recipient_encrypted is None
    assert transaction.airtime_network is None
    assert client.post.await_count == 1

    print("DATA SUCCESS TEST: PASS")
    print("Local reference preserved:", transaction.reference)
    print("Provider ID saved:", transaction.provider_transaction_id)
    print("Provider calls:", client.post.await_count)


def test_timeout_stays_pending():
    db = make_fake_db()

    client = make_async_client(
        error=httpx.TimeoutException("simulated timeout")
    )

    with (
        patch.object(main, "RIDAMSUB_PURCHASES_ENABLED", True),
        patch.object(main, "ridamsub_headers", return_value={"Authorization": "Token mock"}),
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
        patch.object(
            main,
            "apply_provider_result",
            side_effect=mock_apply_provider_result(db),
        ),
    ):
        result = asyncio.run(
            main.execute_ridamsub_purchase(
                db=db,
                user_id=3,
                purchase_type="data",
                network="mtn",
                phone="08012345678",
                idempotency_key="ridam-data-timeout-001",
                plan_id=6,
            )
        )

    transaction = db.saved_transaction

    assert result["status"] == main.PENDING_REQUERY
    assert transaction.status == main.PENDING_REQUERY
    assert bool(transaction.reference)
    assert client.post.await_count == 1

    print("TIMEOUT TEST: PASS")
    print("Transaction remains:", transaction.status)
    print("Local reference preserved:", transaction.reference)
    print("Provider calls (no retry):", client.post.await_count)


def test_airtime_recipient_encryption():
    db = make_fake_db()

    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.text = '{"Status": "successful"}'
    fake_response.json.return_value = {
        "Status": "successful",
        "id": "MOCK-RIDAM-AIRTIME-001",
    }

    client = make_async_client(response=fake_response)

    with (
        patch.object(main, "RIDAMSUB_PURCHASES_ENABLED", True),
        patch.object(main, "ridamsub_headers", return_value={"Authorization": "Token mock"}),
        patch.object(main.httpx, "AsyncClient", return_value=client),
        patch.object(
            main,
            "apply_provider_result",
            side_effect=mock_apply_provider_result(db),
        ),
    ):
        result = asyncio.run(
            main.execute_ridamsub_purchase(
                db=db,
                user_id=3,
                purchase_type="airtime",
                network="mtn",
                phone="08012345678",
                idempotency_key="ridam-airtime-encryption-001",
                amount=Decimal("100.00"),
            )
        )

    transaction = db.saved_transaction

    assert result["status"] == "success"
    assert transaction.status == "success"
    assert transaction.gateway == "ridamsub"

    assert transaction.recipient_encrypted is not None
    assert "08012345678" not in transaction.recipient_encrypted

    assert decrypt_phone_number(
        transaction.recipient_encrypted
    ) == "08012345678"

    assert transaction.airtime_network == "mtn"
    assert client.post.await_count == 1

    print("AIRTIME ENCRYPTION TEST: PASS")
    print("Recipient encrypted and recoverable.")
    print("Network saved correctly:", transaction.airtime_network)
    print("Provider calls:", client.post.await_count)


if __name__ == "__main__":
    test_success()
    test_timeout_stays_pending()
    test_airtime_recipient_encryption()
    print("ALL RIDAMSUB MOCK TESTS PASSED")
