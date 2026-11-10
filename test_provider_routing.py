from decimal import Decimal
from fastapi import HTTPException

from main import (
    resolve_data_provider_and_price,
    resolve_purchase_amount,
)
from providers.gndata_pricing import (
    validate_pricing,
    TOTAL_PLANS,
)

print("\nOMOTECH PROVIDER ROUTING TEST")
print("=" * 40)

# Test 1: GN Data catalogue
assert validate_pricing() is True
print(f"PASS: GN Data pricing catalogue ({TOTAL_PLANS} plans)")

# Test 2: GN Data MTN plan
result = resolve_data_provider_and_price("mtn", 707)
assert result["provider"] == "gndata"
assert result["selling_price"] == Decimal("180.00")
print("PASS: GN Data MTN plan 707 uses your ₦180 price")

# Test 3: GN Data Airtel plan
result = resolve_data_provider_and_price("airtel", 633)
assert result["provider"] == "gndata"
assert result["selling_price"] == Decimal("128.00")
print("PASS: GN Data Airtel plan 633 uses your ₦128 price")

# Test 4: Ridamsub fallback
result = resolve_data_provider_and_price("mtn", 6)
assert result["provider"] == "ridamsub"
assert result["selling_price"] == Decimal("270.00")
print("PASS: Ridamsub MTN plan 6 uses your ₦270 price")

# Test 5: Unsupported plan
try:
    resolve_data_provider_and_price("9mobile", 999999)
    raise AssertionError("Unsupported plan was accepted")
except HTTPException as exc:
    assert exc.status_code == 400
    print("PASS: Unsupported plan rejected")

# Test 6: Purchase amount resolver
amount = resolve_purchase_amount("data", "mtn", 707, None)
assert amount == Decimal("180.00")
print("PASS: Purchase amount resolver uses GN Data selling price")

print("=" * 40)
print("ALL LOCAL ROUTING TESTS PASSED")
