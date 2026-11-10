
import os
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ["OMOTECH_SKIP_CREATE_ALL"] = "1"
os.environ["GNDATA_API_KEY"] = "mock-only-test-credential"

import main


REQUEST = main.AirtimePurchaseRequest(
    network="MTN",
    phone="08030000001",
    amount=100,
)

USER = SimpleNamespace(id=1)


async def call_endpoint():
    return await main.purchase_airtime(
        request=REQUEST,
        current_user=USER,
        db=object(),
        idempotency_key="airtime-routing-test-001",
        background_tasks=None,
    )


def test_gn_selected_first():
    print("\n--- TEST 1: GN selected when available ---")

    gn_result = {
        "reference": "GN-TEST-001",
        "status": "success",
        "amount": 100.0,
    }

    gn_purchase = AsyncMock(return_value=gn_result)
    ridamsub_purchase = AsyncMock()

    fake_gn_client = SimpleNamespace(
        enabled=True,
        api_key="mock-key",
    )

    with (
        patch.object(main, "GNDataClient", return_value=fake_gn_client),
        patch.object(main, "execute_gndata_airtime_purchase", gn_purchase),
        patch.object(main, "execute_ridamsub_purchase", ridamsub_purchase),
        patch.object(main, "validate_idempotency_key", return_value="test-key"),
    ):
        result = asyncio.run(call_endpoint())

    assert result == gn_result
    gn_purchase.assert_awaited_once()
    ridamsub_purchase.assert_not_awaited()

    print("Result:", result)
    print("GN calls:", gn_purchase.await_count)
    print("Ridamsub calls:", ridamsub_purchase.await_count)
    print("PASS: GN selected; Ridamsub not called.")


def test_ridamsub_used_when_gn_unavailable():
    print("\n--- TEST 2: Ridamsub fallback before GN submission ---")

    ridamsub_result = {
        "reference": "RIDAMSUB-TEST-001",
        "status": "success",
        "amount": 100.0,
    }

    gn_purchase = AsyncMock()
    ridamsub_purchase = AsyncMock(return_value=ridamsub_result)

    fake_gn_client = SimpleNamespace(
        enabled=False,
        api_key=None,
    )

    with (
        patch.object(main, "GNDataClient", return_value=fake_gn_client),
        patch.object(main, "execute_gndata_airtime_purchase", gn_purchase),
        patch.object(main, "execute_ridamsub_purchase", ridamsub_purchase),
        patch.object(main, "RIDAMSUB_PURCHASES_ENABLED", True),
        patch.object(main, "validate_idempotency_key", return_value="test-key"),
    ):
        result = asyncio.run(call_endpoint())

    assert result == ridamsub_result
    gn_purchase.assert_not_awaited()
    ridamsub_purchase.assert_awaited_once()

    print("Result:", result)
    print("GN calls:", gn_purchase.await_count)
    print("Ridamsub calls:", ridamsub_purchase.await_count)
    print("PASS: Ridamsub selected because GN was unavailable before submission.")


def test_gn_uncertain_result_never_falls_back():
    print("\n--- TEST 3: GN uncertain result must not trigger Ridamsub ---")

    pending_result = {
        "reference": "GN-TEST-PENDING",
        "transaction_type": "airtime",
        "amount": 100.0,
        "status": "PENDING_REQUERY",
        "message": "Purchase is being verified. Do not retry.",
    }

    gn_purchase = AsyncMock(return_value=pending_result)
    ridamsub_purchase = AsyncMock()

    fake_gn_client = SimpleNamespace(
        enabled=True,
        api_key="mock-key",
    )

    with (
        patch.object(main, "GNDataClient", return_value=fake_gn_client),
        patch.object(main, "execute_gndata_airtime_purchase", gn_purchase),
        patch.object(main, "execute_ridamsub_purchase", ridamsub_purchase),
        patch.object(main, "validate_idempotency_key", return_value="test-key"),
    ):
        result = asyncio.run(call_endpoint())

    assert result["status"] == "PENDING_REQUERY"
    gn_purchase.assert_awaited_once()
    ridamsub_purchase.assert_not_awaited()

    print("Result:", result)
    print("GN calls:", gn_purchase.await_count)
    print("Ridamsub calls:", ridamsub_purchase.await_count)
    print("PASS: GN pending result returned; no Ridamsub fallback.")


if __name__ == "__main__":
    test_gn_selected_first()
    test_ridamsub_used_when_gn_unavailable()
    test_gn_uncertain_result_never_falls_back()

    print("\nALL GN AIRTIME ROUTING TESTS PASSED.")
