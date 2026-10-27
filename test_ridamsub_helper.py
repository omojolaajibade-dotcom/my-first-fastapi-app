
from decimal import Decimal
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException

import main


def make_fake_db():
    db = Mock()
    db.add.side_effect = lambda transaction: setattr(
        db, "saved_transaction", transaction
    )
    db.refresh.side_effect = lambda transaction: None
    return db


def test_success():
    db = make_fake_db()

    fake_response = Mock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "Status": "successful",
        "id": "MOCK-RIDAM-001",
    }

    with (
        patch.object(main, "RIDAMSUB_API_KEY", "mock-test-key"),
        patch.object(main.httpx, "post", return_value=fake_response) as post,
    ):
        result = main.execute_ridamsub_purchase(
            db=db,
            user_id=3,
            network="mtn",
            phone="08012345678",
            local_amount=Decimal("300.00"),
            plan_id=6,
        )

    transaction = db.saved_transaction

    assert result["status"] == "success"
    assert result["provider_transaction_id"] == "MOCK-RIDAM-001"
    assert transaction.status == "success"
    assert transaction.reference == result["reference"]
    assert post.call_count == 1

    print("SUCCESS TEST: PASS")
    print("Local reference preserved:", transaction.reference)
    print("Provider ID returned:", result["provider_transaction_id"])
    print("Provider calls:", post.call_count)


def test_timeout_stays_pending():
    db = make_fake_db()

    with (
        patch.object(main, "RIDAMSUB_API_KEY", "mock-test-key"),
        patch.object(
            main.httpx,
            "post",
            side_effect=httpx.TimeoutException("simulated timeout"),
        ) as post,
    ):
        try:
            main.execute_ridamsub_purchase(
                db=db,
                user_id=3,
                network="mtn",
                phone="08012345678",
                local_amount=Decimal("300.00"),
                plan_id=6,
            )
        except HTTPException as exc:
            assert exc.status_code == 504
            assert exc.detail["status"] == "pending"
        else:
            raise AssertionError("Expected a timeout HTTPException")

    transaction = db.saved_transaction

    assert transaction.status == "pending"
    assert bool(transaction.reference)
    assert db.commit.call_count == 1
    assert post.call_count == 1

    print("TIMEOUT TEST: PASS")
    print("Transaction remains:", transaction.status)
    print("Local reference preserved:", transaction.reference)
    print("Database commits:", db.commit.call_count)
    print("Provider calls (no retry):", post.call_count)


if __name__ == "__main__":
    test_success()
    test_timeout_stays_pending()
    print("ALL MOCK TESTS PASSED")
