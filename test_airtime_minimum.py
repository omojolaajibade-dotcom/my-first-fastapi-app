
import asyncio
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import patch

import main


class ReachedIdempotencyValidation(Exception):
    pass


def stop_before_provider(key):
    raise ReachedIdempotencyValidation()


async def test_amount(amount):
    request = main.AirtimePurchaseRequest(
        network="MTN",
        phone="08030000001",
        amount=amount,
    )

    user = SimpleNamespace(id=999999)

    return await main.purchase_airtime(
        request=request,
        current_user=user,
        db=None,
        idempotency_key="minimum-test-key",
        background_tasks=None,
    )


def run_test():
    original_flag = main.AIRTIME_PURCHASES_ENABLED
    main.AIRTIME_PURCHASES_ENABLED = True

    try:
        with patch.object(
            main,
            "validate_idempotency_key",
            side_effect=stop_before_provider,
        ):
            # Amounts below ₦100 must be rejected.
            for amount in [50, 99]:
                try:
                    main.AirtimePurchaseRequest(
                        network="MTN",
                        phone="08030000001",
                        amount=amount,
                    )
                    raise AssertionError(
                        f"₦{amount} should have been rejected"
                    )
                except ValidationError:
                    print(
                        f"PASS: ₦{amount} rejected by request model"
                    )

            # Amounts from ₦100 upwards must pass validation.
            for amount in [
                100, 151, 160, 250,
                500, 1000, 10000, 100000
            ]:
                try:
                    asyncio.run(test_amount(amount))
                except ReachedIdempotencyValidation:
                    print(
                        f"PASS: ₦{amount} passed minimum validation"
                    )
                else:
                    raise AssertionError(
                        f"₦{amount} did not reach expected test checkpoint"
                    )

    finally:
        main.AIRTIME_PURCHASES_ENABLED = original_flag


if __name__ == "__main__":
    run_test()
