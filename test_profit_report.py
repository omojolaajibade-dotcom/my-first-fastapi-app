
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSession = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

main.Base.metadata.create_all(bind=engine)
db = TestSession()

try:
    transactions = [
        ("ridamsub", "airtime_purchase", "100.00", "98.00"),
        ("ridamsub", "data_purchase", "388.00", "330.00"),
        ("gndata", "data_purchase", "498.00", "377.40"),
        ("gndata", "airtime_purchase", "50.00", None),
    ]

    for index, (gateway, service, sale, cost) in enumerate(transactions):
        db.add(
            main.WalletTransaction(
                user_id=1,
                transaction_type=service,
                amount=Decimal(sale),
                provider_cost=Decimal(cost) if cost is not None else None,
                status="success",
                reference=f"LOCAL-PROFIT-VERIFY-{index}",
                gateway=gateway,
            )
        )

    # Add records that must be excluded from the report.
    db.add(
        main.WalletTransaction(
            user_id=1,
            transaction_type="airtime_purchase",
            amount=Decimal("500.00"),
            provider_cost=Decimal("490.00"),
            status="pending",
            reference="LOCAL-PROFIT-VERIFY-PENDING",
            gateway="ridamsub",
        )
    )

    db.add(
        main.WalletTransaction(
            user_id=1,
            transaction_type="wallet_funding",
            amount=Decimal("1000.00"),
            status="success",
            reference="LOCAL-PROFIT-VERIFY-FUNDING",
            gateway="paystack",
        )
    )

    db.commit()

    report = main.admin_profit_report(
        current_admin=SimpleNamespace(id=1),
        db=db,
    )

    assert report["total_transactions"] == 4
    assert report["total_sales"] == 1036.00
    assert report["sales_with_known_cost"] == 986.00
    assert report["total_provider_cost"] == 805.40
    assert report["gross_profit"] == 180.60
    assert report["unknown_cost_sales"] == 50.00
    assert report["unknown_cost_transactions"] == 1

    assert report["providers"]["ridamsub"]["sales"] == 488.00
    assert report["providers"]["ridamsub"]["gross_profit"] == 60.00

    assert report["providers"]["gndata"]["sales"] == 548.00
    assert report["providers"]["gndata"]["gross_profit"] == 120.60
    assert report["providers"]["gndata"]["unknown_cost_sales"] == 50.00

    assert report["services"]["airtime"]["sales"] == 150.00
    assert report["services"]["airtime"]["gross_profit"] == 2.00
    assert report["services"]["data"]["sales"] == 886.00
    assert report["services"]["data"]["gross_profit"] == 178.60

    print("\nPROFIT REPORT TEST RESULTS")
    print("==========================")
    print("Successful transactions:", report["total_transactions"])
    print("Total sales:             ₦", report["total_sales"])
    print("Sales with known cost:   ₦", report["sales_with_known_cost"])
    print("Provider costs:          ₦", report["total_provider_cost"])
    print("Gross profit:            ₦", report["gross_profit"])
    print("Unknown-cost sales:      ₦", report["unknown_cost_sales"])
    print("Unknown-cost transactions:", report["unknown_cost_transactions"])
    print("\nPASS: Ridamsub and GN Data calculations are correct.")
    print("PASS: Airtime and data calculations are correct.")
    print("PASS: Unknown provider costs are not treated as zero.")
    print("PASS: Pending transactions and wallet funding are excluded.")

finally:
    db.close()
    main.Base.metadata.drop_all(bind=engine)
    engine.dispose()
