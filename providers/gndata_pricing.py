from decimal import Decimal

NETWORKS = {
    "mtn": {"network_id": 26, "name": "MTN"},
    "airtel": {"network_id": 27, "name": "Airtel"},
    "glo": {"network_id": 28, "name": "Glo"},
    "9mobile": {"network_id": 29, "name": "9mobile"},
}

# Format:
# network_id|plan_id|name|type|validity|provider_cost|selling_price
_RAW_PLANS = """
26|707|75MB|Gifting|24 hours|79.56|180
26|708|110MB|Gifting|1 day|104.04|210
26|724|2.5GB|Gifting|2 days|902.70|1220
26|726|3.2GB|Gifting|2 days|1005.72|1250
26|709|500MB|Gifting|7 days|224.40|355
26|612|1GB|SME|7 days|377.40|498
26|613|2GB|SME|7 days|698.70|810
26|714|1GB|Gifting|7 days|796.62|950
26|614|3GB|SME|7 days|994.50|1220
26|728|6GB|Gifting|7 days|2510.22|2790
26|729|11GB|Gifting|7 days|3528.18|3900
26|733|20GB|Gifting|7 days|5202.00|5500
26|615|1GB|Corporate|30 days|402.90|460
26|617|2GB|Corporate|30 days|754.80|1100
26|616|3GB|Corporate|30 days|1030.20|1250
26|625|5GB|SME|30 days|1407.60|1720
26|744|10GB|Corporate|30 days|2866.20|3120
26|745|15GB|Corporate|30 days|4295.22|4500
26|730|10GB|Gifting|30 days|4503.30|4800
26|731|12.5GB|Gifting|30 days|5505.96|5700
26|746|20GB|Corporate|30 days|5722.20|5910
26|734|75GB|Gifting|30 days|18237.60|19000
26|735|200GB|Gifting|60 days|53601.00|56000
27|633|150MB|SME|1 day|61.20|128
27|750|150MB|Coupon|1 day*|61.20|128
27|636|300MB|SME|2 days|122.40|526
27|640|600MB|SME|1 day|229.50|359
27|637|300MB|SME|2 days|304.98|450
27|641|1GB Social bundle|Social|3 days|304.98|400
27|646|1.5GB|SME|1 day|446.76|650
27|652|3GB|SME|2 days|754.80|950
27|649|2GB|SME|2 days|724.20|952
27|756|3GB|Coupon|2 days*|765.00|958
27|759|500MB|Coupon|7 days*|504.90|760
27|647|1.5GB Social bundle|Social|7 days|501.84|759
27|639|500MB|Gifting|7 days|506.94|600
27|645|1GB|Gifting|7 days|805.80|905
27|760|1GB|Coupon|7 days*|804.78|904
27|648|1.5GB|Gifting|7 days|843.54|950
27|656|4GB|Gifting|7 days|1499.40|1800
27|659|6GB|Gifting|7 days|2402.10|2600
27|663|10GB|Gifting|7 days|2896.80|3050
27|669|18GB|Gifting|7 days|5038.80|5800
27|668|18GB|Gifting|7 days|5038.80|5800
27|677|60GB|Gifting|7 days|15147.00|16500
27|769|2GB|Coupon|30 days*|1509.60|1900
27|650|2GB|Corporate|30 days|1499.40|1800
27|655|3GB|Corporate|30 days|1912.50|2200
27|770|3GB|Coupon|30 days*|2014.50|2300
27|657|4GB|Corporate|30 days|2391.90|2700
27|771|4GB|Coupon|30 days*|2519.40|2800
27|661|8GB|Corporate|30 days|2886.60|3200
27|772|8GB|Coupon|30 days*|3049.80|3300
27|762|10GB|Coupon|30 days*|3315.00|3600
27|761|10GB|Coupon|30 days*|3315.00|3600
27|664|10GB Pay loan before sending|Corporate|30 days|3162.00|3500
27|773|10GB|Coupon|30 days*|4039.20|4250
27|666|13GB|Corporate|30 days|4809.30|5000
27|774|13GB|Coupon|30 days*|5064.30|5250
27|763|13GB MIFI|Coupon|30 days*|5145.90|5500
27|775|18GB|Coupon|30 days*|6089.40|6600
27|671|18GB|Corporate|30 days|5783.40|6000
27|672|25GB|Corporate|30 days|7716.30|8000
27|776|25GB|Coupon|30 days*|8124.30|8600
27|765|35GB MIFI|Coupon|30 days*|10327.50|10700
27|766|35GB MIFI|Coupon|30 days*|10327.50|10700
27|674|35GB|Corporate|30 days|10072.50|10600
27|676|60GB|Corporate|30 days|15147.00|15800
27|779|100GB|Coupon|30 days*|20502.00|21000
27|678|100GB|Corporate|30 days|20298.00|21000
28|682|750MB|SME|1 day|210.12|290
28|688|1.5GB|SME|1 day|306.00|420
28|686|1GB|SME|1 day|352.92|400
28|683|1GB|SME|3 days|362.10|400
28|691|2.5GB|SME|2 days|489.60|650
28|689|2GB|SME|1 day|499.80|670
28|692|3GB|SME|3 days|912.90|1300
28|696|5GB|SME|3 days|1402.50|1700
28|680|200MB|SME|14 days|92.82|150
28|684|1GB|Gifting|7 days|374.34|400
28|693|3GB|Gifting|7 days|994.50|1400
28|697|5GB|Gifting|7 days|1657.50|2200
28|698|5GB Night|Gifting|14 days|1708.50|2200
28|700|10GB|Gifting|7 days|1938.00|2300
28|702|10GB|Gifting|14 days|3417.00|3700
28|681|500MB|Corporate|30 days|206.04|300
28|687|1GB|Corporate|30 days|405.96|460
28|690|2GB|Corporate|30 days|811.92|959
28|695|3GB|Corporate|30 days|1217.88|1500
28|699|5GB|Corporate|30 days|2029.80|2300
28|780|10GB|Corporate|30 days|2993.70|3300
28|704|12GB|Corporate|30 days|3870.90|4300
28|705|16GB|Corporate|30 days|4839.90|5200
28|706|20GB|Corporate|30 days|5793.60|6300
"""

GN_DATA_PLANS = {
    26: {},
    27: {},
    28: {},
    29: {},
}

for line in _RAW_PLANS.strip().splitlines():
    network_id, plan_id, name, plan_type, validity, cost, selling = line.split("|")
    network_id = int(network_id)
    plan_id = int(plan_id)

    GN_DATA_PLANS[network_id][plan_id] = {
        "plan_id": plan_id,
        "network_id": network_id,
        "network": NETWORKS[str(network_id) if False else {
            26: "mtn",
            27: "airtel",
            28: "glo",
            29: "9mobile",
        }[network_id]]["name"],
        "name": name,
        "plan_type": plan_type,
        "validity": validity,
        "provider_cost": Decimal(cost),
        "selling_price": Decimal(selling),
    }


def get_network_plans(network_id):
    """Return all configured plans for a GN Data network ID."""
    return tuple(GN_DATA_PLANS.get(int(network_id), {}).values())


def get_plan(plan_id, network_id=None):
    """Find a plan by ID, optionally restricting the network."""
    plan_id = int(plan_id)

    if network_id is not None:
        return GN_DATA_PLANS.get(int(network_id), {}).get(plan_id)

    for plans in GN_DATA_PLANS.values():
        if plan_id in plans:
            return plans[plan_id]

    return None


def get_selling_price(plan_id, network_id=None):
    """Return the configured customer selling price as Decimal."""
    plan = get_plan(plan_id, network_id)
    if plan is None:
        raise ValueError(f"GN Data plan ID {plan_id} is not configured")
    return plan["selling_price"]


def validate_pricing():
    """Check catalogue counts, unique IDs, and price margins."""
    expected_counts = {26: 23, 27: 47, 28: 24, 29: 0}

    for network_id, expected in expected_counts.items():
        actual = len(GN_DATA_PLANS[network_id])
        if actual != expected:
            raise ValueError(
                f"Network {network_id}: expected {expected} plans, found {actual}"
            )

    for plans in GN_DATA_PLANS.values():
        for plan in plans.values():
            if plan["selling_price"] <= plan["provider_cost"]:
                raise ValueError(
                    f"Plan {plan['plan_id']} selling price must exceed provider cost"
                )

    return True


TOTAL_PLANS = sum(len(plans) for plans in GN_DATA_PLANS.values())
