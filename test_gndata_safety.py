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

main.SessionLocal = TestSession

class FakeGNDataClient:
    enabled = True
    api_key = "mock-only-test-credential"
    calls = 0

    async def purchase_data(self, **kwargs):
        self.calls += 1
        return {
            "status": "success",
            "request_id": "MOCK-GNDATA-001",
        }

fake_client = FakeGNDataClient()

db = TestSession()

try:
    user = main.User(
        name="GN Data Test Customer",
        phone="08030000001",
        wallet_balance=Decimal("1000.00"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    with patch.object(
        main,
        "GNDataClient",
        return_value=fake_client,
    ), patch.object(
        main,
        "get_plan",
       return_value={
    "plan_id": 6,
    "provider_cost": "100.00",
    "selling_price": "150.00",
    },

    ), patch.dict(
        main.GN_DATA_NETWORKS,
        {"mtn": {"network_id": 1, "name": "MTN"}},
    ):
        result = asyncio.run(
            main.execute_gndata_purchase(
                db=db,
                user_id=user.id,
                network="mtn",
                phone="08030000001",
                idempotency_key="mock-success-test-001",
                plan_id=6,
            )
        )

    db.refresh(user)

    transaction = (
        db.query(main.WalletTransaction)
        .filter_by(
            user_id=user.id,
            idempotency_key="mock-success-test-001",
        )
        .first()
    )

    print("Purchase result:", result)
    print("Wallet balance:", user.wallet_balance)
    print("Transaction status:", transaction.status if transaction else None)
    print("Provider calls:", fake_client.calls)

    assert result["status"] == "success"
    assert user.wallet_balance == Decimal("850.00")
    assert transaction is not None
    assert transaction.status == "success"
    assert fake_client.calls == 1

    print("\nPASS: Mocked successful purchase test.")

finally:
    db.close()
    engine.dispose()


# TEST 2: Duplicate idempotency protection

print("\n--- TEST 2: Duplicate purchase protection ---")

duplicate_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
)
DuplicateSession = sessionmaker(bind=duplicate_engine)

main.Base.metadata.create_all(
    bind=duplicate_engine,
    tables=[main.User.__table__, main.WalletTransaction.__table__],
)
main.SessionLocal = DuplicateSession

duplicate_db = DuplicateSession()
duplicate_client = FakeGNDataClient()

try:
    duplicate_user = main.User(
        name="Duplicate Test Customer",
        phone="08030000002",
        wallet_balance=Decimal("1000.00"),
    )
    duplicate_db.add(duplicate_user)
    duplicate_db.commit()
    duplicate_db.refresh(duplicate_user)

    with patch.object(
        main, "GNDataClient", return_value=duplicate_client
    ), patch.object(
        main, "get_plan",
return_value={
    "plan_id": 6,
    "provider_cost": "100.00",
    "selling_price": "150.00",
},
           ), patch.dict(
        main.GN_DATA_NETWORKS,
        {"mtn": {"network_id": 1, "name": "MTN"}},
    ):
        first_result = asyncio.run(
            main.execute_gndata_purchase(
                db=duplicate_db,
                user_id=duplicate_user.id,
                network="mtn",
                phone="08030000002",
                idempotency_key="duplicate-test-001",
                plan_id=6,
            )
        )

        second_result = asyncio.run(
            main.execute_gndata_purchase(
                db=duplicate_db,
                user_id=duplicate_user.id,
                network="mtn",
                phone="08030000002",
                idempotency_key="duplicate-test-001",
                plan_id=6,
            )
        )

    duplicate_db.refresh(duplicate_user)

    transaction_count = duplicate_db.query(
        main.WalletTransaction
    ).filter_by(user_id=duplicate_user.id).count()

    print("First result:", first_result)
    print("Second result:", second_result)
    print("Wallet balance:", duplicate_user.wallet_balance)
    print("Transaction count:", transaction_count)
    print("Provider calls:", duplicate_client.calls)

    assert duplicate_user.wallet_balance == Decimal("850.00")
    assert transaction_count == 1
    assert duplicate_client.calls == 1
    assert second_result["reference"] == first_result["reference"]

    print("PASS: Duplicate request did not cause another debit or provider call.")

finally:
    duplicate_db.close()
    duplicate_engine.dispose()



# TEST 3: Reject reused idempotency key with different phone

print("\n--- TEST 3: Idempotency key misuse ---")

test3_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
)
Test3Session = sessionmaker(bind=test3_engine)

main.Base.metadata.create_all(
    bind=test3_engine,
    tables=[main.User.__table__, main.WalletTransaction.__table__],
)

main.SessionLocal = Test3Session
test3_db = Test3Session()
test3_client = FakeGNDataClient()

try:
    test3_user = main.User(
        name="Idempotency Test Customer",
        phone="08030000003",
        wallet_balance=Decimal("1000.00"),
    )
    test3_db.add(test3_user)
    test3_db.commit()
    test3_db.refresh(test3_user)

    with patch.object(
        main, "GNDataClient", return_value=test3_client
    ), patch.object(
        main, "get_plan",
        return_value={
    "plan_id": 6,
    "provider_cost": "100.00",
    "selling_price": "150.00",
},
    ), patch.dict(
        main.GN_DATA_NETWORKS,
        {"mtn": {"network_id": 1, "name": "MTN"}},
    ):
        first_result = asyncio.run(
            main.execute_gndata_purchase(
                db=test3_db,
                user_id=test3_user.id,
                network="mtn",
                phone="08030000003",
                idempotency_key="misuse-test-001",
                plan_id=6,
            )
        )

        try:
            asyncio.run(
                main.execute_gndata_purchase(
                    db=test3_db,
                    user_id=test3_user.id,
                    network="mtn",
                    phone="08030000099",
                    idempotency_key="misuse-test-001",
                    plan_id=6,
                )
            )
            raise AssertionError("Expected HTTP 409 was not raised.")

        except HTTPException as exc:
            assert exc.status_code == 409
            print("Second request rejected with HTTP 409.")

    test3_db.refresh(test3_user)

    count = test3_db.query(
        main.WalletTransaction
    ).filter_by(user_id=test3_user.id).count()

    print("Wallet balance:", test3_user.wallet_balance)
    print("Transaction count:", count)
    print("Provider calls:", test3_client.calls)

    assert test3_user.wallet_balance == Decimal("850.00")
    assert count == 1
    assert test3_client.calls == 1

    print("PASS: Different phone number was rejected safely.")

finally:
    test3_db.close()
    test3_engine.dispose()


# TEST 4: Insufficient wallet balance

print("\n--- TEST 4: Insufficient wallet balance ---")

test4_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
)
Test4Session = sessionmaker(bind=test4_engine)

main.Base.metadata.create_all(
    bind=test4_engine,
    tables=[main.User.__table__, main.WalletTransaction.__table__],
)

test4_db = Test4Session()
test4_client = FakeGNDataClient()

try:
    test4_user = main.User(
        name="Insufficient Balance Customer",
        phone="08030000004",
        wallet_balance=Decimal("100.00"),
    )
    test4_db.add(test4_user)
    test4_db.commit()
    test4_db.refresh(test4_user)

    with patch.object(
        main, "GNDataClient", return_value=test4_client
    ), patch.object(
        main, "get_plan",
        return_value={
    "plan_id": 6,
    "provider_cost": "100.00",
    "selling_price": "150.00",
},
    ), patch.dict(
        main.GN_DATA_NETWORKS,
        {"mtn": {"network_id": 1, "name": "MTN"}},
    ):
        try:
            asyncio.run(
                main.execute_gndata_purchase(
                    db=test4_db,
                    user_id=test4_user.id,
                    network="mtn",
                    phone="08030000004",
                    idempotency_key="insufficient-test-001",
                    plan_id=6,
                )
            )
            raise AssertionError("Expected HTTP 400 was not raised.")

        except HTTPException as exc:
            assert exc.status_code == 400
            print("Insufficient balance rejected with HTTP 400.")

    test4_db.refresh(test4_user)

    count = test4_db.query(
        main.WalletTransaction
    ).filter_by(user_id=test4_user.id).count()

    print("Wallet balance:", test4_user.wallet_balance)
    print("Transaction count:", count)
    print("Provider calls:", test4_client.calls)

    assert test4_user.wallet_balance == Decimal("100.00")
    assert count == 0
    assert test4_client.calls == 0

    print("PASS: Insufficient balance caused no debit or provider request.")

finally:
    test4_db.close()
    test4_engine.dispose()



# TEST 5: Provider timeout must remain pending

print("\n--- TEST 5: Provider timeout ---")

test5_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
)
Test5Session = sessionmaker(bind=test5_engine)

main.Base.metadata.create_all(
    bind=test5_engine,
    tables=[main.User.__table__, main.WalletTransaction.__table__],
)

test5_db = Test5Session()

class TimeoutGNDataClient:
    enabled = True
    api_key = "mock-only-test-credential"
    calls = 0

    async def purchase_data(self, **kwargs):
        self.calls += 1
        raise main.GNDataError("Simulated provider timeout")

test5_client = TimeoutGNDataClient()
patcher5 = patch.object(main, "SessionLocal", Test5Session)
patcher5.start()

try:
    test5_user = main.User(
        name="Provider Timeout Customer",
        phone="08030000005",
        wallet_balance=Decimal("1000.00"),
    )
    test5_db.add(test5_user)
    test5_db.commit()
    test5_db.refresh(test5_user)

    with patch.object(
        main, "GNDataClient", return_value=test5_client
    ), patch.object(
        main, "get_plan",
        return_value={
    "plan_id": 6,
    "provider_cost": "100.00",
    "selling_price": "150.00",
},
    ), patch.dict(
        main.GN_DATA_NETWORKS,
        {"mtn": {"network_id": 1, "name": "MTN"}},
    ):
        result = asyncio.run(
            main.execute_gndata_purchase(
                db=test5_db,
                user_id=test5_user.id,
                network="mtn",
                phone="08030000005",
                idempotency_key="timeout-test-001",
                plan_id=6,
            )
        )

    test5_db.refresh(test5_user)

    transaction = test5_db.query(
        main.WalletTransaction
    ).filter_by(
        user_id=test5_user.id,
        idempotency_key="timeout-test-001",
    ).first()

    print("Purchase result:", result)
    print("Wallet balance:", test5_user.wallet_balance)
    print("Transaction status:", transaction.status if transaction else None)
    print("Provider calls:", test5_client.calls)

    assert result["status"] == main.PENDING_REQUERY
    assert test5_user.wallet_balance == Decimal("850.00")
    assert transaction is not None
    assert transaction.status == main.PENDING_REQUERY
    assert test5_client.calls == 1

    print("PASS: Timeout remained pending without another provider request.")

finally:
    patcher5.stop()
    test5_db.close()
    test5_engine.dispose()


# TEST 6: Definitive failure and exactly-once refund

print("\n--- TEST 6: Failure and exactly-once refund ---")

test6_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
)
Test6Session = sessionmaker(bind=test6_engine)

main.Base.metadata.create_all(
    bind=test6_engine,
    tables=[main.User.__table__, main.WalletTransaction.__table__],
)

patcher6 = patch.object(main, "SessionLocal", Test6Session)
patcher6.start()

test6_db = Test6Session()

class FailedGNDataClient:
    enabled = True
    api_key = "mock-only-test-credential"
    calls = 0

    async def purchase_data(self, **kwargs):
        self.calls += 1
        return {
            "status": "failed",
            "request_id": "MOCK-FAIL-001",
        }

test6_client = FailedGNDataClient()

try:
    test6_user = main.User(
        name="Refund Test Customer",
        phone="08030000006",
        wallet_balance=Decimal("1000.00"),
    )
    test6_db.add(test6_user)
    test6_db.commit()
    test6_db.refresh(test6_user)

    with patch.object(
        main, "GNDataClient", return_value=test6_client
    ), patch.object(
        main, "get_plan",
        return_value={
    "plan_id": 6,
    "provider_cost": "100.00",
    "selling_price": "150.00",
},
    ), patch.dict(
        main.GN_DATA_NETWORKS,
        {"mtn": {"network_id": 1, "name": "MTN"}},
    ):
        result = asyncio.run(
            main.execute_gndata_purchase(
                db=test6_db,
                user_id=test6_user.id,
                network="mtn",
                phone="08030000006",
                idempotency_key="refund-test-001",
                plan_id=6,
            )
        )

    test6_db.refresh(test6_user)

    transaction = test6_db.query(
        main.WalletTransaction
    ).filter_by(
        user_id=test6_user.id,
        idempotency_key="refund-test-001",
    ).first()

    print("Purchase result:", result)
    print("Wallet after failure:", test6_user.wallet_balance)
    print("Transaction status:", transaction.status if transaction else None)
    print("Provider calls:", test6_client.calls)

    assert transaction is not None
    assert transaction.status == "failed"
    assert test6_user.wallet_balance == Decimal("1000.00")
    assert test6_client.calls == 1

    main.apply_provider_result(
        transaction.reference,
        "failed",
        gateway="gndata",
    )

    test6_db.expire_all()
    test6_user = test6_db.query(main.User).filter_by(
        id=test6_user.id
    ).first()

    print("Wallet after repeated failure result:", test6_user.wallet_balance)

    assert test6_user.wallet_balance == Decimal("1000.00")
    assert test6_client.calls == 1

    print("PASS: Failure refunded once; repeated result caused no second refund.")

finally:
    patcher6.stop()
    test6_db.close()
    test6_engine.dispose()
