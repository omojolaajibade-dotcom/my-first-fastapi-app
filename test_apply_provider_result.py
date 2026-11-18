import os
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OMOTECH_SKIP_CREATE_ALL"] = "1"

import main

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


def create_transaction(reference, gateway, balance, debited):
    db = TestSession()

    create_transaction.counter = getattr(create_transaction, "counter", 0) + 1
    user = main.User(
        name="Wallet Handler Test",
        phone=f"0803000{create_transaction.counter:04d}",
        wallet_balance=Decimal(balance),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    tx = main.WalletTransaction(
        user_id=user.id,
        transaction_type="airtime_purchase",
        amount=Decimal("100.00"),
        status="pending",
        reference=reference,
        gateway=gateway,
        wallet_debited=debited,
    )
    db.add(tx)
    db.commit()

    user_id = user.id
    db.close()
    return user_id


def check_wallet(user_id):
    db = TestSession()
    user = db.query(main.User).filter_by(id=user_id).first()
    result = Decimal(str(user.wallet_balance))
    db.close()
    return result


def check_debited(reference):
    db = TestSession()
    tx = db.query(main.WalletTransaction).filter_by(
        reference=reference
    ).first()
    result = tx.wallet_debited
    db.close()
    return result


try:
    for gateway in ("gndata", "ridamsub"):

        # Test confirmed success: debit exactly once.
        ref = f"SUCCESS_{gateway}"
        uid = create_transaction(
            ref, gateway, "1000.00", False
        )

        result = main.apply_provider_result(
            ref, "success", gateway=gateway
        )
        assert result["status"] == "success"
        assert check_wallet(uid) == Decimal("900.00")
        assert check_debited(ref) is True

        main.apply_provider_result(
            ref, "success", gateway=gateway
        )
        assert check_wallet(uid) == Decimal("900.00")

        print(f"PASS: {gateway} success debited exactly once.")

        # Test new purchase failure: no debit or refund.
        ref = f"FAILURE_{gateway}"
        uid = create_transaction(
            ref, gateway, "1000.00", False
        )

        result = main.apply_provider_result(
            ref, "failed", gateway=gateway
        )
        assert result["status"] == "failed"
        assert check_wallet(uid) == Decimal("1000.00")
        assert check_debited(ref) is False

        print(f"PASS: {gateway} failure caused no debit.")

        # Test legacy purchase: refund an existing debit once.
        ref = f"LEGACY_{gateway}"
        uid = create_transaction(
            ref, gateway, "900.00", True
        )

        result = main.apply_provider_result(
            ref, "failed", gateway=gateway
        )
        assert result["status"] == "failed"
        assert result["refunded"] is True
        assert check_wallet(uid) == Decimal("1000.00")
        assert check_debited(ref) is False

        main.apply_provider_result(
            ref, "failed", gateway=gateway
        )
        assert check_wallet(uid) == Decimal("1000.00")

        print(f"PASS: {gateway} legacy refund applied exactly once.")

    print("\nALL WALLET RESULT HANDLER TESTS PASSED.")

finally:
    engine.dispose()