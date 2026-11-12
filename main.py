import os



import secrets



import hashlib



import hmac



import json



import requests



from decimal import Decimal



from datetime import datetime, timedelta, timezone



import jwt



import uuid



import httpx



from fastapi import Header



from dotenv import load_dotenv



from fastapi import HTTPException



from config import RIDAMSUB_NETWORKS, RIDAMSUB_DATA_PLANS

from providers.gndata import GNDataClient, GNDataError
from providers.gndata_pricing import (
    NETWORKS as GN_DATA_NETWORKS,
    get_network_plans,
    get_plan,
    get_selling_price,
    validate_pricing,
)



from fastapi import Depends, FastAPI, HTTPException, Request, Query



from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer



from fastapi.responses import FileResponse, RedirectResponse



from pydantic import BaseModel, Field, EmailStr



from sqlalchemy import (

    Column, DateTime, Integer, String, Boolean, Numeric,

    create_engine, func, update

)

from sqlalchemy.orm import declarative_base, sessionmaker, Session



from pwdlib import PasswordHash



# =========================

# LOAD ENVIRONMENT VARIABLES

# =========================



load_dotenv()

from security import (
    encrypt_phone_number,
    decrypt_phone_number,
    hash_phone_number,
)



# =========================

# DATABASE, JWT AND PAYSTACK CONFIGURATION

# =========================



DATABASE_URL = os.getenv("DATABASE_URL")



if not DATABASE_URL:

    raise RuntimeError("DATABASE_URL is not configured")



JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")

RIDAMSUB_API_KEY = os.getenv("RIDAMSUB_API_KEY")

RIDAMSUB_BASE_URL = "https://ridamsub.com"

# VENDING: ENABLED FOR CONTROLLED LIVE TESTING.

RIDAMSUB_PURCHASES_ENABLED = True

# These statuses must be confirmed against Ridamsub's

# documented API contract before enabling automatic refunds.

RIDAMSUB_DEFINITIVE_REJECTION_STATUSES = {

    "failed",

    "rejected",

}

PAYSTACK_BASE_URL = "https://api.paystack.co"



if not JWT_SECRET_KEY:

    raise RuntimeError("JWT_SECRET_KEY is not configured")



if not PAYSTACK_SECRET_KEY:

    raise RuntimeError("PAYSTACK_SECRET_KEY is not configured")



JWT_ALGORITHM = "HS256"

JWT_EXPIRE_MINUTES = 60





# =========================

# DATABASE SETUP

# =========================



engine = create_engine(DATABASE_URL)



SessionLocal = sessionmaker(

    autocommit=False,

    autoflush=False,

    bind=engine

)



Base = declarative_base()





def get_db():

    db = SessionLocal()



    try:

        yield db



    finally:

        db.close()





# =========================

# USER MODEL

# =========================



class User(Base):

    __tablename__ = "users"



    id = Column(

        Integer,

        primary_key=True,

        index=True

    )



    name = Column(

        String(100),

        nullable=False

    )



    phone = Column(
    String(255),
    unique=True,
    nullable=False,
    index=True
)

    phone_hash = Column(
    String(64),
    unique=True,
    nullable=True,
    index=True
)


    email = Column(

        String(255),

        nullable=True,

        index=True

    )



    password_hash = Column(

        String(255),

        nullable=True

    )



    wallet_balance = Column(Numeric(12, 2), nullable=False, default=0.00)



    created_at = Column(

        DateTime,

        nullable=False,

        server_default=func.current_timestamp()

    )



# =========================

# ADMIN MODEL

# =========================



class Admin(Base):

    __tablename__ = "admins"



    id = Column(

        Integer,

        primary_key=True,

        index=True

    )



    username = Column(

        String(100),

        unique=True,

        nullable=False,

        index=True

    )



    email = Column(

        String(255),

        nullable=True)



    password_hash = Column(

        String(255),

        nullable=False

    )



    is_active = Column(

        Boolean,

        nullable=False,

        default=True

    )



    wallet_balance = Column(

        Numeric(12, 2),

        nullable=False,

        default=Decimal("0.00"),

        server_default="0.00"

    )



    created_at = Column(

        DateTime,

        nullable=False,

        server_default=func.current_timestamp()

    )







# =========================

# ADMIN AUDIT LOG MODEL

# =========================



class AdminAuditLog(Base):

    __tablename__ = "admin_audit_logs"



    id = Column(

        Integer,

        primary_key=True,

        index=True

    )





    admin_id = Column(

    Integer,

    nullable=False,

    index=True

)





    user_id = Column(

        Integer,

        nullable=True,

        index=True

    )



    action = Column(

    String(50),

    nullable=False,

    index=True

)



    amount = Column(

        Numeric,

        nullable=True

    )



    reason = Column(

    String(255),

    nullable=False

    )



    reference = Column(

    String(100),

    nullable=True,

    unique=True

)



    created_at = Column(

        DateTime,

        nullable=False,

        server_default=func.current_timestamp(),

        index=True

    )





# =========================

# PASSWORD RESET TOKEN MODEL

# =========================



class PasswordResetToken(Base):

    __tablename__ = "password_reset_tokens"



    id = Column(

        Integer,

        primary_key=True,

        index=True

    )



    user_id = Column(

        Integer,

        nullable=False

    )



    token_hash = Column(

        String(255),

        nullable=False

    )



    expires_at = Column(

        DateTime,

        nullable=False

    )



    used = Column(

        Boolean,

        nullable=False,

        default=False

    )



    created_at = Column(

        DateTime,

        nullable=False,

        server_default=func.current_timestamp()

    )







class WalletTransaction(Base):

    __tablename__ = "wallet_transactions"



    id = Column(Integer, primary_key=True, index=True)



    # A transaction belongs to a customer OR an admin.

    user_id = Column(Integer, nullable=True, index=True)

    admin_id = Column(Integer, nullable=True, index=True)



    transaction_type = Column(String(30), nullable=False)

    amount = Column(Numeric(12, 2), nullable=False)
    provider_cost = Column(Numeric(12, 2), nullable=True)

    status = Column(String(20), nullable=False, default="pending")

    reference = Column(String(100), unique=True, nullable=False)

    gateway = Column(String(30), nullable=True)



     # Provider transaction tracking (Ridamsub and GN Data)

    provider_transaction_id = Column(String(100), nullable=True, index=True)

    idempotency_key = Column(String(100), nullable=True)
    request_fingerprint = Column(String(64), nullable=True)



    created_at = Column(

        DateTime,

        nullable=False,

        server_default=func.current_timestamp()

    )



# Create tables during normal startup, but let Alembic

# manage schema changes when running migrations.

if os.getenv("OMOTECH_SKIP_CREATE_ALL") != "1":

    Base.metadata.create_all(bind=engine)



# ============================================================

# RIDAMSUB PURCHASE + RECONCILIATION

# Uses the existing User, WalletTransaction, SessionLocal,

# get_db, get_current_user and RIDAMSUB_DATA_PLANS definitions.

# ============================================================



import asyncio

import logging

import os

from decimal import Decimal, InvalidOperation

from urllib.parse import quote



import httpx

from fastapi import BackgroundTasks, Depends, HTTPException

from sqlalchemy.orm import Session



logger = logging.getLogger(__name__)



RIDAMSUB_BASE_URL = os.getenv(

    "RIDAMSUB_BASE_URL", "https://ridamsub.com"

).rstrip("/")



PENDING_REQUERY = "PENDING_REQUERY"



NETWORK_IDS = {

    "mtn": 1,

    "glo": 2,

    "9mobile": 3,

    "airtel": 4,

}





def ridamsub_headers():

    """Read credentials from the environment on each request."""

    token = os.environ.get("RIDAMSUB_API_KEY")

    if not token:

        raise RuntimeError("RIDAMSUB_API_KEY is not configured")



    return {

        "Authorization": f"Token {token}",

        "Content-Type": "application/json",

    }







def normalize_provider_status(response_json):

    """Safely normalize Ridamsub purchase response statuses."""

    if not isinstance(response_json, dict):

        return PENDING_REQUERY



    # Support both response field formats.

    value = (

        response_json.get("Status")

        or response_json.get("status")

    )



    if not isinstance(value, str):

        return PENDING_REQUERY



    value = value.strip().lower()



    # Confirmed success indicators.

    if value in {"successful", "success", "completed"}:

        return "success"



    # Definitive failure indicators.

    if value in {"fail", "failed", "failure", "reversed"}:

        return "failed"



    # Pending, processing, and unknown responses remain unresolved.

    return PENDING_REQUERY



def normalize_gndata_status(response_json):
    """Safely normalize GN Data transaction statuses."""

    if not isinstance(response_json, dict):
        return PENDING_REQUERY

    value = response_json.get("status")

    if not isinstance(value, str):
        return PENDING_REQUERY

    value = value.strip().lower()

    if value == "success":
        return "success"

    if value in {"failed", "refund"}:
        return "failed"

    # Pending and unknown responses remain unresolved.
    return PENDING_REQUERY






def resolve_data_provider_and_price(network, plan_id):
    """
    Select GN Data first when it offers the requested plan.
    Otherwise, select Ridamsub.
    Return the customer's configured selling price.
    """
    network_key = str(network).strip().lower()

    # Check GN Data first.
    gn_network = GN_DATA_NETWORKS.get(network_key)

    if gn_network:
        gn_network_id = int(gn_network["network_id"])

        gn_plan = get_plan(
            plan_id,
            network_id=gn_network_id,
        )

        if gn_plan is not None:
            price = Decimal(str(gn_plan["selling_price"]))

            if not price.is_finite() or price <= 0:
                raise HTTPException(
                    status_code=500,
                    detail="Invalid GN Data selling price configuration.",
                )

            return {
                "provider": "gndata",
                "network_id": gn_network_id,
                "plan_id": int(gn_plan["plan_id"]),
                "selling_price": price.quantize(Decimal("0.01")),
                "plan": gn_plan,
            }

    # If GN Data does not offer the plan, check Ridamsub.
    ridamsub_plan = next(
        (
            plan
            for plan in RIDAMSUB_DATA_PLANS.get(network_key, [])
            if str(plan.get("plan_id")) == str(plan_id)
            and plan.get("available", True) is True
        ),
        None,
    )

    if ridamsub_plan is not None:
        try:
            price = Decimal(str(ridamsub_plan["selling_price"]))
        except (InvalidOperation, TypeError, ValueError, KeyError):
            price = None

        if price is not None and price.is_finite() and price > 0:
            return {
                "provider": "ridamsub",
                "network_id": RIDAMSUB_NETWORKS.get(network_key),
                "plan_id": int(ridamsub_plan["plan_id"]),
                "selling_price": price.quantize(Decimal("0.01")),
                "plan": ridamsub_plan,
            }

    raise HTTPException(
        status_code=400,
        detail="Requested data plan is not available from our providers.",
    )


def resolve_purchase_amount(purchase_type, network, plan_id, amount):
    """Determine the customer charge before touching the wallet."""

    if purchase_type == "airtime":
        try:
            result = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Invalid airtime amount.",
            )

        if not result.is_finite() or result <= 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid airtime amount.",
            )

        return result.quantize(Decimal("0.01"))

    if purchase_type != "data":
        raise HTTPException(
            status_code=400,
            detail="Unsupported purchase type.",
        )

    selection = resolve_data_provider_and_price(network, plan_id)

    return selection["selling_price"]





def apply_provider_result(reference, provider_status, gateway="ridamsub"):

    """

    Apply a provider result under row locks.



    A definitive failure and its refund are committed atomically.

    Only a pending transaction can be refunded by this routine.

    """

    db = SessionLocal()



    try:

        tx = (

            db.query(WalletTransaction)

            .filter(

                WalletTransaction.reference == reference,

                WalletTransaction.gateway == gateway,

            )

            .with_for_update()

            .first()

        )



        if tx is None:

            db.rollback()

            return {"status": "not_found"}



        # A terminal result must never be applied a second time.

        if tx.status in {"success", "failed"}:

            db.rollback()

            return {"status": tx.status}



        if tx.status not in {"pending", PENDING_REQUERY}:

            db.rollback()

            return {"status": tx.status}



        if provider_status == PENDING_REQUERY:

            tx.status = PENDING_REQUERY

            db.commit()

            return {"status": PENDING_REQUERY}



        if provider_status == "success":

            tx.status = "success"

            db.commit()

            return {"status": "success"}



        if provider_status != "failed":

            db.rollback()

            return {"status": PENDING_REQUERY}



        # Lock and credit the customer in the same transaction.

        user = (

            db.query(User)

            .filter(User.id == tx.user_id)

            .with_for_update()

            .first()

        )



        if user is None:

            db.rollback()

            logger.error(

                "Refund blocked: customer missing for reference %s",

                reference,

            )

            return {"status": PENDING_REQUERY}



        user.wallet_balance = (

            Decimal(str(user.wallet_balance))

            + Decimal(str(tx.amount))

        )

        tx.status = "failed"



        db.commit()

        return {"status": "failed", "refunded": True}



    except Exception:

        db.rollback()

        logger.exception("Could not apply provider result for %s", reference)

        return {"status": PENDING_REQUERY}



    finally:

        db.close()





async def query_ridamsub_status(purchase_type, reference):

    """

    Query transaction status only. This function never creates a purchase.

    Confirm the provider's documented status endpoint before production use.


    """

    if purchase_type not in {"airtime", "data"}:

        return PENDING_REQUERY



    endpoint = "topup" if purchase_type == "airtime" else "data"

    url = (

        f"{RIDAMSUB_BASE_URL}/api/{endpoint}/"

        f"{quote(reference, safe='')}/"

    )



    try:

        async with httpx.AsyncClient(timeout=10.0) as client:

            response = await client.get(

                url,

                headers=ridamsub_headers(),

            )



        if response.status_code != 200:

            logger.warning(

                "Ridamsub status query HTTP %s for %s",

                response.status_code,

                reference,

            )

            return PENDING_REQUERY



        try:

            return normalize_provider_status(response.json())

        except ValueError:

            return PENDING_REQUERY



    except (httpx.HTTPError, RuntimeError):

        logger.exception("Status query failed for %s", reference)

        return PENDING_REQUERY

async def query_gndata_status(request_id):

    """

    Query GN Data transaction status only.
    Never creates or repeats a purchase.
    """

    if not isinstance(request_id, str) or not request_id.strip():
        return PENDING_REQUERY

    try:
        client = GNDataClient()

        response_json = await client.transaction_status(
            request_id
        )

        return normalize_gndata_status(response_json)

    except GNDataError:
        logger.exception(
            "GN Data status query failed for request ID %s",
            request_id,
        )
        return PENDING_REQUERY

    except Exception:
        logger.exception(
            "Unexpected GN Data status query error for %s",
            request_id,
        )
        return PENDING_REQUERY






async def reconcile_pending_transaction(reference, expected_type, user_id=None):
    """
    Reconcile a transaction after an uncertain outcome.

    Status checks only. Never repeats a purchase.
    """
    db = SessionLocal()

    try:
        tx = (
            db.query(WalletTransaction)
            .filter(
                WalletTransaction.reference == reference,
                WalletTransaction.transaction_type
                == f"{expected_type}_purchase",
            )
            .first()
        )

        if tx is None or (
            user_id is not None and tx.user_id != user_id
        ):
            return {"status": "not_found"}

        if tx.status in {"success", "failed"}:
            return {"status": tx.status}

        gateway = tx.gateway
        provider_request_id = tx.provider_transaction_id

    finally:
        db.close()

    if gateway == "ridamsub":
        provider_status = await query_ridamsub_status(
            expected_type, reference
        )
        result = apply_provider_result(reference, provider_status)

    elif gateway == "gndata":
        if not provider_request_id:
            return {"status": PENDING_REQUERY}

        provider_status = await query_gndata_status(
            provider_request_id
        )
        result = apply_provider_result(
            reference,
            provider_status,
            gateway="gndata",
        )

    else:
        logger.error(
            "Unsupported gateway %s for reference %s",
            gateway,
            reference,
        )
        return {"status": PENDING_REQUERY}

    # Recheck ownership, transaction type, and gateway.
    if user_id is not None:
        check_db = SessionLocal()
        try:
            check = (
                check_db.query(WalletTransaction)
                .filter(
                    WalletTransaction.reference == reference
                )
                .first()
            )

            if (
                check is None
                or check.user_id != user_id
                or check.transaction_type
                != f"{expected_type}_purchase"
                or check.gateway != gateway
            ):
                return {"status": "not_found"}

        finally:
            check_db.close()

    return result




async def background_reconcile(reference, expected_type):
    """
    Retry transaction STATUS CHECKS only.
    Never submit another purchase request.
    """
    for attempt in range(3):
        try:
            result = await reconcile_pending_transaction(
                reference, expected_type
            )

            if result.get("status") != PENDING_REQUERY:
                logger.info(
                    "Provider reconciliation completed for %s: %s",
                    reference,
                    result.get("status"),
                )
                return result

        except Exception:
            logger.exception(
                "Provider reconciliation attempt %s failed for %s",
                attempt + 1,
                reference,
            )

        if attempt < 2:
            await asyncio.sleep(2 ** attempt)

    logger.warning(
        "Provider transaction remains pending: %s",
        reference,
    )

    return {"status": PENDING_REQUERY}

def generate_purchase_fingerprint(
    purchase_type: str,
    network: str,
    phone: str,
    amount: Decimal,
    gateway: str,
    plan_id: int | None = None,
    airtime_type: str = "VTU",
) -> str:
    """Generate a stable SHA-256 fingerprint for a purchase request."""

    purchase_details = {
        "purchase_type": str(purchase_type).strip().lower(),
        "network": str(network).strip().lower(),
        "phone": str(phone).strip(),
        "amount": format(
            Decimal(str(amount)).quantize(Decimal("0.01")),
            "f",
        ),
        "gateway": str(gateway).strip().lower(),
        "plan_id": int(plan_id) if plan_id is not None else None,
        "airtime_type": str(airtime_type).strip().upper(),
    }

    canonical_request = json.dumps(
        purchase_details,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(
        canonical_request.encode("utf-8")
    ).hexdigest()




async def execute_ridamsub_purchase(

    db: Session,

    user_id: int,

    purchase_type: str,

    network: str,

    phone: str,

    idempotency_key: str,

    plan_id: int | None = None,

    amount: Decimal | None = None,

    airtime_type: str = "VTU",

    background_tasks: BackgroundTasks | None = None,

):

    """

    Reserve wallet funds, create one local transaction,

    submit one Ridamsub purchase request, and record its response.



    Never repeat a purchase POST when its outcome is uncertain.

    """



    if not RIDAMSUB_PURCHASES_ENABLED:

        raise HTTPException(

            status_code=503,

            detail="Ridamsub purchases are disabled.",

        )



    try:

        headers = ridamsub_headers()

    except RuntimeError:

        raise HTTPException(

            status_code=503,

            detail="Ridamsub API configuration is unavailable.",

        )



    if purchase_type not in {"airtime", "data"}:

        raise HTTPException(

            status_code=400,

            detail="Invalid purchase type.",

        )



    if not idempotency_key or not idempotency_key.strip():

        raise HTTPException(

            status_code=400,

            detail="An idempotency key is required.",

        )



    network_key = network.strip().lower()

    network_id = NETWORK_IDS.get(network_key)



    if network_id is None:

        raise HTTPException(

            status_code=400,

            detail="Unsupported network.",

        )



    final_amount = resolve_purchase_amount(

        purchase_type,

        network_key,

        plan_id,

        amount,

    )



    provider_cost = None

    if purchase_type == "airtime":
        ridamsub_airtime_rates = {
            "mtn": Decimal("0.98"),
            "glo": Decimal("0.99"),
            "9mobile": Decimal("0.98"),
            "airtel": Decimal("0.99"),
        }

        rate = ridamsub_airtime_rates.get(network_key)

        if rate is not None:
            calculated_cost = (
                Decimal(str(final_amount)) * rate
            ).quantize(Decimal("0.01"))

            if calculated_cost.is_finite() and calculated_cost > 0:
                provider_cost = calculated_cost

    elif purchase_type == "data":
        ridamsub_plan = next(
            (
                plan
                for plan in RIDAMSUB_DATA_PLANS.get(network_key, [])
                if str(plan.get("plan_id")) == str(plan_id)
                and plan.get("available", True) is True
            ),
            None,
        )

        if ridamsub_plan is None:
            raise HTTPException(
                status_code=400,
                detail="Ridamsub data plan not found.",
            )

        try:
            provider_cost = Decimal(
                str(ridamsub_plan["provider_cost"])
            ).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError, KeyError):
            raise HTTPException(
                status_code=500,
                detail="Invalid Ridamsub provider cost configuration.",
            )

        if not provider_cost.is_finite() or provider_cost <= 0:
            raise HTTPException(
                status_code=500,
                detail="Invalid Ridamsub provider cost configuration.",
            )

        if (
            provider_cost is None
            or not provider_cost.is_finite()
            or provider_cost <= 0
        ):
            raise HTTPException(
            status_code=500,
            detail="Unable to determine a valid provider cost. Purchase was not submitted.",
        )



        if (
            provider_cost is None
            or not provider_cost.is_finite()
            or provider_cost <= 0
        ):
            raise HTTPException(
                status_code=500,
                detail=(
                    "Unable to determine a valid provider cost. "
                    "Purchase was not submitted."
            ),
        )



    request_fingerprint = generate_purchase_fingerprint(
        purchase_type=purchase_type,
        network=network_key,
        phone=phone,
        amount=final_amount,
        gateway="ridamsub",
        plan_id=plan_id,
        airtime_type=airtime_type,
    )



    local_ref = (

        f"OMOTECH_{purchase_type.upper()}_{secrets.token_hex(12)}"

    )



    # Reserve funds and check duplicate requests.

    try:

        user = (

            db.query(User)

            .filter(User.id == user_id)

            .with_for_update()

            .first()

        )



        if user is None:

            raise HTTPException(

                status_code=404,

                detail="User not found.",

            )



        # Prevent a repeated request from creating another purchase.

        existing_tx = (

            db.query(WalletTransaction)

            .filter(

                WalletTransaction.user_id == user_id,

                WalletTransaction.idempotency_key == idempotency_key,

            )

            .order_by(WalletTransaction.id.desc())

            .first()

        )



        if existing_tx:

            if (
               existing_tx.gateway != "ridamsub"
               or not existing_tx.request_fingerprint
               or existing_tx.request_fingerprint != request_fingerprint

            ):
               raise HTTPException(
                   status_code=409,
                   detail=(
                       "This idempotency key was already used for a "
                       "different or unverifiable purchase. "
                       "Use a new idempotency key."
                    ),
            )

            existing_result = {
                "reference": existing_tx.reference,
                "transaction_type": existing_tx.transaction_type,
                "amount": str(existing_tx.amount),
                "status": existing_tx.status,
                "message": (
                    "This purchase request has already been recorded. "
                    "Do not submit it again."
                 ),
            }

            db.rollback()

            return existing_result


        current_balance = Decimal(str(user.wallet_balance))



        if current_balance < final_amount:

            raise HTTPException(

                status_code=400,

                detail="Insufficient wallet balance.",

            )



        user.wallet_balance = current_balance - final_amount



        tx = WalletTransaction(

            user_id=user_id,

            transaction_type=f"{purchase_type}_purchase",

            amount=final_amount,

            provider_cost=provider_cost,

            status="pending",

            reference=local_ref,

            gateway="ridamsub",

            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,

        )



        db.add(tx)

        db.commit()

        db.refresh(tx)



    except HTTPException:

        db.rollback()

        raise



    except Exception:

        db.rollback()

        logger.exception(

            "Could not reserve wallet funds for Ridamsub purchase."

        )

        raise HTTPException(

            status_code=500,

            detail="Could not create the purchase transaction.",

        )



    # Build purchase request.

    if purchase_type == "airtime":

        endpoint = "/api/topup/"

        payload = {

            "network": network_id,

            "amount": int(final_amount),

            "mobile_number": phone,

            "Ported_number": True,

            "airtime_type": airtime_type,

            "request-id": local_ref,

        }



    else:

        endpoint = "/api/data/"

        payload = {

            "network": network_id,

            "mobile_number": phone,

            "plan": plan_id,

            "Ported_number": True,

            "request-id": local_ref,

        }



    # Submit exactly one purchase POST.

    provider_status = PENDING_REQUERY



    try:

        async with httpx.AsyncClient(timeout=20.0) as client:

            response = await client.post(

                f"{RIDAMSUB_BASE_URL}{endpoint}",

                headers=headers,

                json=payload,

            )



        try:

            response_json = response.json()

        except ValueError:

            response_json = None



        logger.info(

            "Ridamsub %s response: HTTP %s | Body: %s",

            purchase_type,

            response.status_code,

            response.text[:1000],

        )



        if response.status_code >= 400:

            provider_status = PENDING_REQUERY

        else:

            provider_status = normalize_provider_status(

                response_json

            )



        # Capture a possible provider transaction identifier.

        if isinstance(response_json, dict):

            provider_id = (

                response_json.get("ident")

                or response_json.get("transaction_id")

                or response_json.get("transid")

                or response_json.get("id")

            )



            if provider_id is not None:

                try:

                    tx.provider_transaction_id = str(provider_id)[:100]

                    db.commit()



                    logger.info(

                        "Saved Ridamsub provider ID for %s",

                        local_ref,

                    )



                except Exception:

                    db.rollback()

                    logger.exception(

                        "Could not save Ridamsub provider ID for %s",

                        local_ref,

                    )

                    provider_status = PENDING_REQUERY



    except httpx.HTTPError:

        logger.exception(

            "Ridamsub purchase outcome uncertain: %s",

            local_ref,

        )

        provider_status = PENDING_REQUERY



    except Exception:

        logger.exception(

            "Unexpected Ridamsub purchase error: %s",

            local_ref,

        )

        provider_status = PENDING_REQUERY



    # Apply the provider result to the existing transaction.

    result = apply_provider_result(

        local_ref,

        provider_status,

    )



    if (

        result.get("status") == PENDING_REQUERY

        and background_tasks is not None

    ):

        background_tasks.add_task(

            background_reconcile,

            local_ref,

            purchase_type,

        )



    return {

        "reference": local_ref,

        "transaction_type": f"{purchase_type}_purchase",

        "amount": str(final_amount),

        "status": result.get("status", PENDING_REQUERY),

        "message": (

            "Purchase confirmed."

            if result.get("status") == "success"

            else "The transaction is being reconciled. Do not retry the purchase."

        ),

    }



async def submit_ridamsub_airtime_fallback(
    db: Session,
    transaction: WalletTransaction,
    network: str,
    phone: str,
    amount: Decimal,
    airtime_type: str = "VTU",
    background_tasks: BackgroundTasks | None = None,
):
    """Submit an existing GN airtime transaction to Ridamsub without a second debit."""

    local_ref = transaction.reference
    network_key = network.strip().lower()

    # GN has definitively rejected the request, so refund if fallback
    # cannot safely be submitted.
    if not RIDAMSUB_PURCHASES_ENABLED:
        return apply_provider_result(
            local_ref, "failed", gateway="gndata"
        )

    network_id = NETWORK_IDS.get(network_key)
    if network_id is None:
        return apply_provider_result(
            local_ref, "failed", gateway="gndata"
        )

    try:
        headers = ridamsub_headers()
    except Exception:
        logger.exception(
            "Ridamsub fallback configuration unavailable: %s",
            local_ref,
        )
        return apply_provider_result(
            local_ref, "failed", gateway="gndata"
        )

    rates = {
        "mtn": Decimal("0.98"),
        "glo": Decimal("0.99"),
        "9mobile": Decimal("0.98"),
        "airtel": Decimal("0.99"),
    }

    rate = rates.get(network_key)
    if rate is None:
        return apply_provider_result(
            local_ref, "failed", gateway="gndata"
        )

    provider_cost = (
        amount * rate
    ).quantize(Decimal("0.01"))

    # Switch the existing transaction to Ridamsub.
    # Keep its original GN request fingerprint unchanged.
    transaction.gateway = "ridamsub"
    transaction.provider_cost = provider_cost

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Could not prepare Ridamsub fallback: %s",
            local_ref,
        )
        return apply_provider_result(
            local_ref, "failed", gateway="gndata"
        )

    payload = {
        "network": network_id,
        "amount": int(amount),
        "mobile_number": phone,
        "Ported_number": True,
        "airtime_type": airtime_type,
        "request-id": local_ref,
    }

    provider_status = PENDING_REQUERY

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{RIDAMSUB_BASE_URL}/api/topup/",
                headers=headers,
                json=payload,
            )

        try:
            response_json = response.json()
        except ValueError:
            response_json = None

        logger.info(
            "Ridamsub airtime fallback: HTTP %s | Reference %s",
            response.status_code,
            local_ref,
        )

        if response.status_code < 400:
            provider_status = normalize_provider_status(response_json)

            if isinstance(response_json, dict):
                provider_id = (
                    response_json.get("ident")
                    or response_json.get("transaction_id")
                    or response_json.get("transid")
                    or response_json.get("id")
                )

                if provider_id is not None:
                    try:
                        transaction.provider_transaction_id = (
                            str(provider_id)[:100]
                        )
                        db.commit()
                    except Exception:
                        db.rollback()
                        logger.exception(
                            "Could not save Ridamsub fallback provider ID: %s",
                            local_ref,
                        )
                        provider_status = PENDING_REQUERY

    except Exception:
        db.rollback()
        logger.exception(
            "Ridamsub airtime fallback outcome uncertain: %s",
            local_ref,
        )
        provider_status = PENDING_REQUERY

    result = apply_provider_result(
        local_ref,
        provider_status,
        gateway="ridamsub",
    )

    if (
        result.get("status") == PENDING_REQUERY
        and background_tasks is not None
    ):
        background_tasks.add_task(
            background_reconcile,
            local_ref,
            "airtime",
        )

    return result



async def execute_gndata_airtime_purchase(
    db: Session,
    user_id: int,
    network: str,
    phone: str,
    amount,
    idempotency_key: str,
    background_tasks: BackgroundTasks | None = None,
):
    """Execute one GN Data airtime purchase with a single wallet reservation."""

    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise HTTPException(
            status_code=400,
            detail="An idempotency key is required.",
        )

    network_key = str(network).strip().lower()
    gn_network = GN_DATA_NETWORKS.get(network_key)

    if not gn_network:
        raise HTTPException(
            status_code=400,
            detail="Unsupported GN Data airtime network.",
        )

    try:
        final_amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Invalid airtime amount.",
        )

    if (
        not final_amount.is_finite()
        or final_amount <= 0
        or final_amount != final_amount.to_integral_value()
    ):
        raise HTTPException(
            status_code=400,
            detail="Airtime amount must be a positive whole number.",
        )

    gn_amount = int(final_amount)
    network_id = int(gn_network["network_id"])

    client = GNDataClient()

    if not client.enabled or not client.api_key:
        raise HTTPException(
            status_code=503,
            detail="GN Data airtime is currently unavailable.",
        )

    request_fingerprint = generate_purchase_fingerprint(
        purchase_type="airtime",
        network=network_key,
        phone=phone,
        amount=final_amount,
        gateway="gndata",
    )

    local_ref = f"OMOTECH_AIRTIME_{secrets.token_hex(12)}"

    try:
        user = (
            db.query(User)
            .filter(User.id == user_id)
            .with_for_update()
            .first()
        )

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="Customer account not found.",
            )

        existing = (
            db.query(WalletTransaction)
            .filter(
                WalletTransaction.user_id == user_id,
                WalletTransaction.idempotency_key == idempotency_key,
            )
            .first()
        )

        if existing:
            if (
                existing.transaction_type != "airtime_purchase"
                or Decimal(str(existing.amount)) != final_amount
                or existing.gateway not in {"gndata", "ridamsub"}
                or not existing.request_fingerprint
                or existing.request_fingerprint != request_fingerprint
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was already used for another transaction.",
                )

            existing_result = {
                "reference": existing.reference,
                "status": existing.status,
                "amount": float(existing.amount),
                "message": "Existing transaction returned. Do not retry.",
            }

            db.rollback()
            return existing_result

        if Decimal(str(user.wallet_balance)) < final_amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient wallet balance.",
            )

        user.wallet_balance = (
            Decimal(str(user.wallet_balance)) - final_amount
        )

        transaction = WalletTransaction(
            user_id=user_id,
            transaction_type="airtime_purchase",
            amount=final_amount,
            provider_cost=None,
            status="pending",
            reference=local_ref,
            gateway="gndata",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception("Could not reserve wallet funds for GN Data airtime.")
        raise HTTPException(
            status_code=500,
            detail="Unable to initiate airtime purchase.",
        )


    provider_status = PENDING_REQUERY
    provider_reference = None
    fallback_result = None

    try:
        response_json = await client.purchase_airtime(
            phone=phone,
            amount=gn_amount,
            network_id=network_id,
            idempotency_key=idempotency_key,
        )

        provider_reference = (
            response_json.get("request_id")
            or response_json.get("transaction_id")
            or response_json.get("id")
        )

        provider_status = normalize_gndata_status(response_json)

        transaction.provider_transaction_id = (
            str(provider_reference) if provider_reference else None
        )

        db.commit()


    except GNDataError as exc:
        logger.error(
            "GN DATA ACTUAL AIRTIME RESPONSE | "
            "Reference=%s | HTTP=%s | Body=%s",
            local_ref,
            exc.status_code,
            exc.response_body or "<EMPTY RESPONSE BODY>",
        )

        if exc.is_definitive_rejection:
            logger.warning(
                "GN Data definitively rejected airtime request %s; "
                "attempting Ridamsub fallback. HTTP %s",
                local_ref,
                exc.status_code,
            )

            fallback_result = await submit_ridamsub_airtime_fallback(
                db=db,
                transaction=transaction,
                network=network_key,
                phone=phone,
                amount=final_amount,
                airtime_type="VTU",
                background_tasks=background_tasks,
            )
        else:
            logger.exception(
                "GN Data airtime response uncertain for %s",
                local_ref,
            )
            provider_status = PENDING_REQUERY

    except Exception:
        logger.exception(
            "Unexpected GN Data airtime error for %s",
            local_ref,
        )
        provider_status = PENDING_REQUERY



    if fallback_result is not None:
        result = fallback_result
    else:
        result = apply_provider_result(
            local_ref,
            provider_status,
            gateway="gndata",
        )

    if result.get("status") == PENDING_REQUERY and background_tasks:
        if fallback_result is None and provider_reference:
            background_tasks.add_task(
                background_reconcile,
                local_ref,
                "airtime",
            )

    return {
        "reference": local_ref,
        "transaction_type": "airtime",
        "amount": float(final_amount),
        "status": result.get("status", PENDING_REQUERY),
        "message": (
            "Airtime purchase successful."
            if result.get("status") == "success"
            else (
                "Airtime purchase failed. Your wallet has been refunded."
                if result.get("status") == "failed"
                else "Purchase is being verified. Do not retry."
            )
        ),
    }


async def submit_ridamsub_data_fallback(
    db: Session,
    transaction: WalletTransaction,
    network: str,
    phone: str,
    gn_plan: dict,
    background_tasks: BackgroundTasks | None = None,
):
    """Use Ridamsub for an existing GN transaction without another debit."""

    import re

    local_ref = transaction.reference
    network_key = network.strip().lower()
    customer_amount = Decimal(str(transaction.amount))

    def capacity_mb(name):
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*(GB|MB)",
            str(name),
            re.IGNORECASE,
        )
        if not match:
            return None
        value = Decimal(match.group(1))
        return value * 1024 if match.group(2).upper() == "GB" else value


    def bundle_type(name):
        value = str(name).lower()

        if "corporate" in value and "gifting" in value:
            return None

        for kind in (
            "sme", "corporate", "gifting",
            "social", "coupon", "mifi", "awoof"
        ):
            if kind in value:
                return kind

        return None
    def validity_days(value):
        value = str(value).strip().lower().replace("*", "")
        if value in {"daily", "1 day"}:
            return 1
        if value in {"weekly", "7 days", "1 week"}:
            return 7
        if value in {"14 days", "2 weeks"}:
            return 14
        if value in {"monthly", "1 month", "30 days"}:
            return 30
        if value in {"60 days", "2 months"}:
            return 60
        return None

    gn_size = capacity_mb(gn_plan.get("name"))
    gn_type = str(gn_plan.get("plan_type", "")).strip().lower()
    gn_validity = validity_days(gn_plan.get("validity"))

    if not all((gn_size, gn_type, gn_validity)):
        return apply_provider_result(local_ref, "failed", gateway="gndata")

    matching_plan = None

    for candidate in RIDAMSUB_DATA_PLANS.get(network_key, []):
        if candidate.get("available", True) is not True:
            continue

        if capacity_mb(candidate.get("name")) != gn_size:
            continue

        if bundle_type(candidate.get("name")) != gn_type:
            continue

        if validity_days(candidate.get("validity")) != gn_validity:
            continue

        try:
            cost = Decimal(str(candidate["provider_cost"])).quantize(
                Decimal("0.01")
            )
        except (InvalidOperation, TypeError, ValueError, KeyError):
            continue

        if not cost.is_finite() or cost <= 0 or cost > customer_amount:
            continue

        matching_plan = candidate
        break

    if matching_plan is None or not RIDAMSUB_PURCHASES_ENABLED:
        logger.warning("No safe Ridamsub data equivalent for %s", local_ref)
        return apply_provider_result(local_ref, "failed", gateway="gndata")

    try:
        headers = ridamsub_headers()
        network_id = NETWORK_IDS.get(network_key)

        if network_id is None:
            return apply_provider_result(local_ref, "failed", gateway="gndata")

        transaction.gateway = "ridamsub"
        transaction.provider_cost = Decimal(
            str(matching_plan["provider_cost"])
        ).quantize(Decimal("0.01"))
        db.commit()

    except Exception:
        db.rollback()
        logger.exception("Could not prepare Ridamsub data fallback: %s", local_ref)
        return apply_provider_result(local_ref, "failed", gateway="gndata")

    payload = {
        "network": network_id,
        "mobile_number": phone,
        "plan": int(matching_plan["plan_id"]),
        "Ported_number": True,
        "request-id": local_ref,
    }

    provider_status = PENDING_REQUERY

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{RIDAMSUB_BASE_URL}/api/data/",
                headers=headers,
                json=payload,
            )

        try:
            response_json = response.json()
        except ValueError:
            response_json = None

        if response.status_code < 400:
            provider_status = normalize_provider_status(response_json)

            if isinstance(response_json, dict):
                provider_id = (
                    response_json.get("ident")
                    or response_json.get("transaction_id")
                    or response_json.get("transid")
                    or response_json.get("id")
                )
                if provider_id is not None:
                    transaction.provider_transaction_id = str(provider_id)[:100]
                    db.commit()

        logger.info(
            "Ridamsub data fallback response: HTTP %s | Reference %s",
            response.status_code,
            local_ref,
        )

    except Exception:
        db.rollback()
        logger.exception("Ridamsub data fallback outcome uncertain: %s", local_ref)
        provider_status = PENDING_REQUERY

    result = apply_provider_result(
        local_ref,
        provider_status,
        gateway="ridamsub",
    )

    if result.get("status") == PENDING_REQUERY and background_tasks:
        background_tasks.add_task(background_reconcile, local_ref, "data")

    return result




async def execute_gndata_purchase(
    db: Session,
    user_id: int,
    network: str,
    phone: str,
    idempotency_key: str,
    plan_id: int,
    background_tasks: BackgroundTasks | None = None,
):
    """
    Execute one GN Data purchase using the configured selling price.

    The customer is charged only the configured selling_price.
    An uncertain provider response remains pending and is never
    automatically retried through another provider.
    """

    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise HTTPException(
            status_code=400,
            detail="An idempotency key is required.",
        )

    network_key = str(network).strip().lower()
    gn_network = GN_DATA_NETWORKS.get(network_key)

    if not gn_network:
        raise HTTPException(
            status_code=400,
            detail="Unsupported GN Data network.",
        )

    network_id = int(gn_network["network_id"])

    plan = get_plan(plan_id, network_id=network_id)

    if plan is None:
        raise HTTPException(
            status_code=400,
            detail="GN Data plan not found.",
        )

    final_amount = Decimal(str(plan["selling_price"])).quantize(
        Decimal("0.01")
    )


    provider_cost = Decimal(str(plan["provider_cost"])).quantize(
        Decimal("0.01")
    )

    if not provider_cost.is_finite() or provider_cost <= 0:
        raise HTTPException(
            status_code=500,
            detail="Invalid GN Data provider cost.",
        )

    if not final_amount.is_finite() or final_amount <= 0:
        raise HTTPException(
            status_code=500,
            detail="Invalid GN Data selling price.",
        )


    request_fingerprint = generate_purchase_fingerprint(

    purchase_type="data",
    network=network_key,
    phone=phone,
    amount=final_amount,
    gateway="gndata",
    plan_id=int(plan["plan_id"]),
)




    client = GNDataClient()

    if not client.enabled:
        raise HTTPException(
            status_code=503,
            detail="GN Data is currently unavailable.",
        )

    if not client.api_key:
        raise HTTPException(
            status_code=503,
            detail="GN Data credentials are not configured.",
        )

    local_ref = f"OMOTECH_DATA_{secrets.token_hex(12)}"

    try:
        user = (
            db.query(User)
            .filter(User.id == user_id)
            .with_for_update()
            .first()
        )

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="Customer account not found.",
            )

        existing = (
            db.query(WalletTransaction)
            .filter(
                WalletTransaction.user_id == user_id,
                WalletTransaction.idempotency_key == idempotency_key,
            )
            .first()
        )

        if existing:
            if (
                existing.transaction_type != "data_purchase"
                or Decimal(str(existing.amount)) != final_amount
                or existing.gateway not in {"gndata", "ridamsub"}
                or not existing.request_fingerprint
                or existing.request_fingerprint != request_fingerprint
         ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was already used for another transaction.",
                )

            existing_result = {
                "reference": existing.reference,
                "status": existing.status,
                "amount": float(existing.amount),
                "message": "Existing transaction returned. Do not retry.",
            }

            db.rollback()

            return existing_result

        if Decimal(str(user.wallet_balance)) < final_amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient wallet balance.",
            )

        user.wallet_balance = (
            Decimal(str(user.wallet_balance)) - final_amount
        )

        transaction = WalletTransaction(
            user_id=user_id,
            transaction_type="data_purchase",
            amount=final_amount,
            provider_cost=provider_cost,
            status="pending",
            reference=local_ref,
            gateway="gndata",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception("Could not reserve wallet funds for GN Data.")
        raise HTTPException(
            status_code=500,
            detail="Unable to initiate data purchase.",
        )


    provider_status = PENDING_REQUERY
    provider_reference = None
    fallback_result = None

    try:
        response_json = await client.purchase_data(
            phone=phone,
            network_id=network_id,
            plan_id=int(plan["plan_id"]),
            idempotency_key=idempotency_key,
        )

        logger.warning(
            "GN DATA PURCHASE RESPONSE FORMAT | "
            "reference=%s | keys=%s | status=%r | "
            "data_type=%s | data_keys=%s | request_id=%r",
            local_ref,
            sorted(response_json.keys()),
            response_json.get("status"),
            type(response_json.get("data")).__name__,
            sorted(response_json["data"].keys())
            if isinstance(response_json.get("data"), dict)
            else None,
            response_json.get("request_id")
            or response_json.get("transaction_id")
            or response_json.get("id"),
        )

        provider_reference = (
            response_json.get("request_id")
            or response_json.get("transaction_id")
            or response_json.get("id")
        )

        provider_status = normalize_gndata_status(response_json)

        transaction.provider_transaction_id = (
            str(provider_reference) if provider_reference else None
        )
        db.commit()

   
    except GNDataError as exc:
        logger.error(
            "GN DATA ACTUAL DATA RESPONSE | "
            "Reference=%s | HTTP=%s | Body=%s",
            local_ref,
            exc.status_code,
            exc.response_body or "<EMPTY RESPONSE BODY>",
        )

        if exc.is_definitive_rejection:
            logger.warning(
                "GN Data definitively rejected data purchase %s; "
                "attempting Ridamsub fallback. HTTP %s",
                local_ref,
                exc.status_code,
            )

            fallback_result = await submit_ridamsub_data_fallback(
                db=db,
                transaction=transaction,
                network=network_key,
                phone=phone,
                gn_plan=plan,
                background_tasks=background_tasks,
            )
        else:
            logger.exception(
                "GN Data data-purchase outcome uncertain: %s",
                local_ref,
            )
            provider_status = PENDING_REQUERY

    except Exception:
        logger.exception(
            "Unexpected GN Data purchase error for %s",
            local_ref,
        )
        provider_status = PENDING_REQUERY

        provider_status = PENDING_REQUERY
    if fallback_result is not None:
        result = fallback_result
    else:
        result = apply_provider_result(
            local_ref,
            provider_status,
            gateway="gndata",
        )

        if (
            result.get("status") == PENDING_REQUERY
            and background_tasks
            and provider_reference
        ):
            background_tasks.add_task(
                background_reconcile,
                local_ref,
                "data",
            )

    return {
        "reference": local_ref,
        "transaction_type": "data",
        "amount": float(final_amount),
        "status": result.get("status", PENDING_REQUERY),
	 "message": (
            "Data purchase successful."
            if result.get("status") == "success"
            else (
                "Data purchase failed. Your wallet has been refunded."
                if result.get("status") == "failed"
                else "Purchase is being verified. Do not retry."
            )
        ),
}




async def execute_data_purchase(
    db: Session,
    user_id: int,
    network: str,
    phone: str,
    idempotency_key: str,
    plan_id: int,
    background_tasks: BackgroundTasks | None = None,
):
    """
    Automatically select GN Data or Ridamsub before
    reserving wallet funds or submitting a purchase.
    """

    selection = resolve_data_provider_and_price(
        network,
        plan_id,
    )

    provider = selection["provider"]

    if provider == "gndata":
        return await execute_gndata_purchase(
            db=db,
            user_id=user_id,
            network=network,
            phone=phone,
            idempotency_key=idempotency_key,
            plan_id=selection["plan_id"],
            background_tasks=background_tasks,
        )

    if provider == "ridamsub":
        return await execute_ridamsub_purchase(
            db=db,
            user_id=user_id,
            purchase_type="data",
            network=network,
            phone=phone,
            idempotency_key=idempotency_key,
            plan_id=selection["plan_id"],
            background_tasks=background_tasks,
        )

    raise HTTPException(
        status_code=400,
        detail="No provider is available for this data plan.",
    )





# =========================

app = FastAPI(

    title="Omotech Airtime & Data API",

    description="Backend API for the Omotech Airtime & Data application",

    version="1.0.0"

)







@app.get("/api/plans/{network}")

def get_ridamsub_data_plans(network: str):

    network_key = network.strip().lower()



    if network_key not in RIDAMSUB_NETWORKS:

        raise HTTPException(

            status_code=404,

            detail="Unsupported network.",

        )



    customer_plans = []



    for plan in RIDAMSUB_DATA_PLANS.get(network_key, []):

        plan_id = plan.get("plan_id")

        provider_cost = plan.get("provider_cost")

        selling_price = plan.get("selling_price")



        if plan.get("available") is not True:

            continue



        if (

            not isinstance(plan_id, int)

            or isinstance(plan_id, bool)

            or plan_id <= 0

        ):

            continue



        if (

            not isinstance(provider_cost, (int, float))

            or isinstance(provider_cost, bool)

            or provider_cost <= 0

        ):

            continue



        if (

            not isinstance(selling_price, (int, float))

            or isinstance(selling_price, bool)

            or selling_price <= 0

            or selling_price < provider_cost

        ):

            continue



        customer_plans.append({

            "variation_code": str(plan_id),

            "plan_id": plan_id,

            "name": plan["name"],

            "price": selling_price,

            "validity": plan.get("validity", "Not specified"),

        })



    return {

        "network": network_key,

        "network_id": RIDAMSUB_NETWORKS[network_key],

        "plans": customer_plans,

    }







# =========================

# PYDANTIC SCHEMAS

# =========================



class UserCreate(BaseModel):

    name: str = Field(min_length=2, max_length=100)

    phone: str = Field(min_length=10, max_length=20)

    email: EmailStr

    password: str = Field(min_length=8, max_length=128)





class ProfileUpdateRequest(BaseModel):

    name: str = Field(min_length=2, max_length=100)

    email: EmailStr

    phone: str = Field(min_length=10, max_length=20)





class LoginRequest(BaseModel):

    phone: str = Field(

        min_length=10,

        max_length=20

    )

    password: str = Field(

        min_length=8,

        max_length=128

    )







class AdminLoginRequest(BaseModel):

    username: str = Field(

        min_length=3,

        max_length=100

    )



    password: str = Field(

        min_length=8,

        max_length=128

    )



    password: str = Field(

        min_length=8,

        max_length=128

    )



class ForgotPasswordRequest(BaseModel):

    phone: str = Field(

        min_length=10,

        max_length=20

    )



class AdminProfileUpdateRequest(BaseModel):

    username: str = Field(min_length=3, max_length=100)

    email: EmailStr | None = None



class ResetPasswordRequest(BaseModel):

    phone: str = Field(

        min_length=10,

        max_length=20

    )



    reset_token: str = Field(

        min_length=20,

        max_length=200

    )



    new_password: str = Field(

        min_length=8,

        max_length=128

    )

from decimal import Decimal



class FundWalletRequest(BaseModel):

    amount: Decimal = Field(gt=0, le=1000000)





from typing import Literal



class AirtimePurchaseRequest(BaseModel):

    network: Literal["MTN", "Airtel", "Glo", "9mobile"]

    phone: str = Field(pattern=r"^0\d{10}$")

    amount: Decimal = Field(ge=50, le=100000)



class DataPurchaseRequest(BaseModel):

    network: Literal["MTN", "Airtel", "Glo", "9mobile"]

    phone: str = Field(pattern=r"^0\d{10}$")

    variation_code: str = Field(min_length=1, max_length=100)







# =========================

# PASSWORD SECURITY

# =========================



password_hash = PasswordHash.recommended()





# =========================

# JWT TOKEN CREATION

# =========================



def create_access_token(user_id: int):



    expire = datetime.now(timezone.utc) + timedelta(

        minutes=JWT_EXPIRE_MINUTES

    )



    payload = {

        "sub": str(user_id),

        "exp": expire

    }



    token = jwt.encode(

        payload,

        JWT_SECRET_KEY,

        algorithm=JWT_ALGORITHM

    )



    return token





def generate_reset_token():

    return secrets.token_urlsafe(32)





def create_admin_access_token(admin_id: int):

    expire = datetime.now(timezone.utc) + timedelta(

        minutes=JWT_EXPIRE_MINUTES

    )



    payload = {

        "sub": str(admin_id),

        "role": "admin",

        "exp": expire

    }



    return jwt.encode(

        payload,

        JWT_SECRET_KEY,

        algorithm=JWT_ALGORITHM

    )





# =========================

# HTTP BEARER SECURITY

# =========================



security = HTTPBearer()





# =========================

# GET CURRENT AUTHENTICATED USER

# =========================



def get_current_user(

    credentials: HTTPAuthorizationCredentials = Depends(security),

    db: Session = Depends(get_db)

):



    token = credentials.credentials



    try:



        payload = jwt.decode(

            token,

            JWT_SECRET_KEY,

            algorithms=[JWT_ALGORITHM]

        )



        user_id = payload.get("sub")



        if user_id is None:



            raise HTTPException(

                status_code=401,

                detail="Invalid authentication token"

            )



    except jwt.ExpiredSignatureError:



        raise HTTPException(

            status_code=401,

            detail="Authentication token has expired"

        )



    except jwt.InvalidTokenError:



        raise HTTPException(

            status_code=401,

            detail="Invalid authentication token"

        )



    try:



        user_id = int(user_id)



    except (TypeError, ValueError):



        raise HTTPException(

            status_code=401,

            detail="Invalid authentication token"

        )



    user = db.query(User).filter(

        User.id == user_id

    ).first()



    if not user:



        raise HTTPException(

            status_code=401,

            detail="User not found"

        )



    return user





# ============================================================

# VERIFICATION ENDPOINTS

# ============================================================



@app.post("/airtime/verify/{reference}")

async def verify_airtime_purchase(

    reference: str,

    background_tasks: BackgroundTasks,

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

):

    tx = (

        db.query(WalletTransaction)

        .filter(

            WalletTransaction.reference == reference,

            WalletTransaction.user_id == current_user.id,


            WalletTransaction.transaction_type == "airtime_purchase",

        )

        .first()

    )



    if tx is None:

        raise HTTPException(status_code=404, detail="Transaction not found.")



    if tx.status in {"success", "failed"}:

        return {"reference": reference, "status": tx.status}



    result = await reconcile_pending_transaction(

        reference, "airtime", current_user.id

    )



    if result.get("status") == PENDING_REQUERY:

        background_tasks.add_task(

            background_reconcile, reference, "airtime"

        )



    return {"reference": reference, **result}



@app.post("/data/verify/{reference}")

async def verify_data_purchase(

    reference: str,

    background_tasks: BackgroundTasks,

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

):

    tx = (

        db.query(WalletTransaction)

        .filter(

            WalletTransaction.reference == reference,

            WalletTransaction.user_id == current_user.id,


            WalletTransaction.transaction_type == "data_purchase",

        )

        .first()

    )



    if tx is None:

        raise HTTPException(status_code=404, detail="Transaction not found.")



    if tx.status in {"success", "failed"}:

        return {"reference": reference, "status": tx.status}



    result = await reconcile_pending_transaction(

        reference, "data", current_user.id

    )



    if result.get("status") == PENDING_REQUERY:

        background_tasks.add_task(

            background_reconcile, reference, "data"

        )



    return {"reference": reference, **result}







# =========================

# GET CURRENT ADMIN

# =========================



def get_current_admin(

    credentials: HTTPAuthorizationCredentials = Depends(security),

    db: Session = Depends(get_db)

):

    token = credentials.credentials



    try:

        payload = jwt.decode(

            token,

            JWT_SECRET_KEY,

            algorithms=[JWT_ALGORITHM]

        )



        admin_id = payload.get("sub")



        if payload.get("role") != "admin" or admin_id is None:

            raise HTTPException(

                status_code=401,

                detail="Admin authentication required."

            )



        admin_id = int(admin_id)



    except HTTPException:

        raise



    except (jwt.InvalidTokenError, TypeError, ValueError):

        raise HTTPException(

            status_code=401,

            detail="Invalid or expired admin token."

        )



    admin = db.query(Admin).filter(

        Admin.id == admin_id,

        Admin.is_active.is_(True)

    ).first()



    if not admin:

        raise HTTPException(

            status_code=401,

            detail="Admin account not found or inactive."

        )



    return admin







# =========================

# HOME

# =========================



@app.get("/")

def home():

    return RedirectResponse(url="/app", status_code=302)



# =========================

# CREATE USER

# =========================



@app.post("/user")
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    submitted_phone = user_data.phone.strip()
    phone_hash = hash_phone_number(submitted_phone)

    existing_user = db.query(User).filter(
        (User.phone_hash == phone_hash) |
        (User.phone == submitted_phone)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Phone number already registered"
        )

    hashed_password = password_hash.hash(user_data.password)

    new_user = User(
        name=user_data.name,
        phone=encrypt_phone_number(submitted_phone),
        phone_hash=phone_hash,
        email=user_data.email,
        password_hash=hashed_password
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User created successfully",
        "id": new_user.id,
        "name": new_user.name,
        "phone": decrypt_phone_number(new_user.phone),
        "email": new_user.email,
        "created_at": new_user.created_at
    }





# =========================

# LOGIN

# =========================



@app.post("/login")
def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    submitted_phone = login_data.phone.strip()
    phone_hash = hash_phone_number(submitted_phone)

    # First, search encrypted customer records.
    user = db.query(User).filter(
        User.phone_hash == phone_hash
    ).first()

    # Support existing records that are still plaintext.
    if not user:
        user = db.query(User).filter(
            User.phone == submitted_phone,
            User.phone_hash.is_(None)
        ).first()

    if not user or not user.password_hash:
        raise HTTPException(
            status_code=401,
            detail="Invalid phone number or password"
        )

    password_is_correct = password_hash.verify(
        login_data.password,
        user.password_hash
    )

    if not password_is_correct:
        raise HTTPException(
            status_code=401,
            detail="Invalid phone number or password"
        )

    # Upgrade an existing plaintext record after successful login.
    if not user.phone_hash:
        user.phone_hash = phone_hash
        user.phone = encrypt_phone_number(submitted_phone)
        db.commit()
        db.refresh(user)

    access_token = create_access_token(user.id)

    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "id": user.id,
        "name": user.name,
        "phone": decrypt_phone_number(user.phone)
    }






# =========================

# ADMIN LOGIN

# =========================



@app.post("/admin/login")

def admin_login(

    login_data: AdminLoginRequest,

    db: Session = Depends(get_db)

):

    admin = db.query(Admin).filter(

        Admin.username == login_data.username

    ).first()



    if not admin or not admin.is_active:

        raise HTTPException(

            status_code=401,

            detail="Invalid username or password."

        )



    password_is_correct = password_hash.verify(

        login_data.password,

        admin.password_hash

    )



    if not password_is_correct:

        raise HTTPException(

            status_code=401,

            detail="Invalid username or password."

        )



    access_token = create_admin_access_token(admin.id)







    return {

        "message": "Admin login successful.",

        "access_token": access_token,

        "token_type": "bearer",

        "admin": {

            "id": admin.id,

            "username": admin.username

        }

    }







@app.get("/admin/wallet")

def get_admin_wallet(

    current_admin: Admin = Depends(get_current_admin)

):

    return {

        "admin_id": current_admin.id,

        "admin_username": current_admin.username,

        "balance": float(current_admin.wallet_balance)

    }





@app.post("/admin/wallet/fund")

def initialize_admin_wallet_funding(

    request: FundWalletRequest,

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db)

):

    if not PAYSTACK_SECRET_KEY:

        raise HTTPException(

            status_code=503,

            detail="Payment service is not configured."

        )



    if not current_admin.email or not current_admin.email.strip():

        raise HTTPException(

            status_code=400,

            detail="Please add an email address to your admin profile."

        )



    amount = Decimal(str(request.amount))



    if amount != amount.quantize(Decimal("0.01")):

        raise HTTPException(

            status_code=400,

            detail="Amount must have no more than two decimal places."

        )



    reference = secrets.token_urlsafe(24)



    transaction = WalletTransaction(

        user_id=None,

        admin_id=current_admin.id,

        transaction_type="funding",

        amount=amount,

        status="pending",

        reference=reference,

        gateway="paystack"

    )



    audit_log = AdminAuditLog(

        admin_id=current_admin.id,

        user_id=None,

        action="admin_wallet_funding_initialized",

        amount=amount,

        reason="Admin wallet funding initiated through Paystack",

        reference=reference

    )



    try:

        db.add(transaction)

        db.add(audit_log)

        db.commit()

        db.refresh(transaction)

    except Exception:

        db.rollback()

        raise HTTPException(

            status_code=500,

            detail="Unable to create the admin funding transaction."

        )



    payload = {

        "email": current_admin.email.strip(),

        "amount": int(amount * Decimal("100")),

        "reference": reference,

         "callback_url": (

        "https://omotech.com.ng/payment-success?flow=admin"

    ),

        "metadata": {

            "owner_type": "admin",

            "admin_id": current_admin.id,

            "transaction_id": transaction.id

        }

    }



    try:

        response = requests.post(

            f"{PAYSTACK_BASE_URL}/transaction/initialize",

            json=payload,

            headers={

                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",

                "Content-Type": "application/json"

            },

            timeout=15

        )

        response.raise_for_status()

        result = response.json()



    except (requests.RequestException, ValueError):

        # Keep the transaction pending if the outcome is uncertain.

        raise HTTPException(

            status_code=502,

            detail=(

                "Unable to confirm payment initialization. "

                "Check the transaction history before retrying."

            )

        )



    if not result.get("status"):

        transaction.status = "failed"

        try:

            db.commit()

        except Exception:

            db.rollback()



        raise HTTPException(

            status_code=502,

            detail="Paystack could not initialize the payment."

        )



    authorization_url = (

        (result.get("data") or {}).get("authorization_url")

    )



    if not authorization_url:

        raise HTTPException(

            status_code=502,

            detail="Paystack did not return a payment URL."

        )



    return {

        "message": "Admin wallet funding initialized.",

        "status": "pending",

        "reference": reference,

        "amount": float(amount),

        "authorization_url": authorization_url

    }









# =========================

# ADMIN PROFILE MANAGEMENT

# =========================



@app.get("/admin/profile")

def get_admin_profile(

    current_admin: Admin = Depends(get_current_admin)

):

    return {

        "id": current_admin.id,

        "username": current_admin.username,

        "email": current_admin.email,

        "is_active": current_admin.is_active,

        "created_at": current_admin.created_at

    }







@app.put("/admin/profile")

def update_admin_profile(

    request: AdminProfileUpdateRequest,

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db)

):

    new_username = request.username.strip()



    existing_admin = db.query(Admin).filter(

        Admin.username == new_username,

        Admin.id != current_admin.id

    ).first()



    if existing_admin:

        raise HTTPException(

            status_code=409,

            detail="This username is already in use."

        )



    current_admin.username = new_username

    current_admin.email = (

        str(request.email).strip().lower()

        if request.email is not None

        else None

    )





    db.commit()

    db.refresh(current_admin)





    try:

        db.add(

            AdminAuditLog(

                admin_id=current_admin.id,

                action="admin_profile_updated",

                reason="Admin updated their profile."

            )

        )

        db.commit()

    except Exception:

        db.rollback()





    return {

        "message": "Admin profile updated successfully.",

        "admin": {

            "id": current_admin.id,

            "username": current_admin.username,

            "email": current_admin.email,

            "is_active": current_admin.is_active,

            "created_at": current_admin.created_at

        }

    }







# =========================

# FORGOT PASSWORD

# =========================



@app.post("/forgot-password")

def forgot_password(

    request: ForgotPasswordRequest,

    db: Session = Depends(get_db)

):



    submitted_phone = request.phone.strip()
    phone_hash = hash_phone_number(submitted_phone)

    user = db.query(User).filter(
        (User.phone_hash == phone_hash) |
        (
            (User.phone == submitted_phone) &
            (User.phone_hash.is_(None))
        )
    ).first()


    if not user:



        raise HTTPException(

            status_code=404,

            detail="User not found"

        )



    reset_token = generate_reset_token()



    token_hash = hashlib.sha256(

        reset_token.encode()

    ).hexdigest()



    expires_at = datetime.now(timezone.utc) + timedelta(

        minutes=15

    )



    reset_record = PasswordResetToken(

        user_id=user.id,

        token_hash=token_hash,

        expires_at=expires_at

    )



    db.add(reset_record)

    db.commit()



    return {

        "message": "Password reset token generated",

        "reset_token": reset_token,

        "expires_in_minutes": 15

    }

# =========================

# RESET PASSWORD

# =========================



@app.post("/reset-password")

def reset_password(

    request: ResetPasswordRequest,

    db: Session = Depends(get_db)

):



    token_hash = hashlib.sha256(

        request.reset_token.encode()

    ).hexdigest()



    reset_record = db.query(

        PasswordResetToken

    ).filter(

        PasswordResetToken.token_hash == token_hash,

        PasswordResetToken.used == False

    ).order_by(

        PasswordResetToken.created_at.desc()

    ).first()



    if not reset_record:



        raise HTTPException(

            status_code=400,

            detail="Invalid or already used reset token"

        )



    current_time = datetime.now(timezone.utc).replace(

        tzinfo=None

    )



    if reset_record.expires_at < current_time:



        raise HTTPException(

            status_code=400,

            detail="Reset token has expired"

        )



    submitted_phone = request.phone.strip()
    phone_hash = hash_phone_number(submitted_phone)

    user = db.query(User).filter(
        User.id == reset_record.user_id,
        (
            (User.phone_hash == phone_hash) |
            (
                (User.phone == submitted_phone) &
                (User.phone_hash.is_(None))
            )
        )
    ).first()


    if not user:



        raise HTTPException(

            status_code=400,

            detail="Invalid password reset request"

        )



    user.password_hash = password_hash.hash(

        request.new_password

    )



    if not user.phone_hash:
        user.phone_hash = phone_hash
        user.phone = encrypt_phone_number(submitted_phone)



    reset_record.used = True



    db.commit()



    return {

        "message": "Password reset successfully"

    }





# =========================

# GET ALL USERS

# =========================



@app.get("/users")

def get_users(

    db: Session = Depends(get_db)

):



    users = db.query(User).all()



    return [

        {

            "id": user.id,

            "name": user.name,

            "phone": decrypt_phone_number(user.phone),

            "created_at": user.created_at

        }

        for user in users

    ]





# =========================

# ADMIN USER MANAGEMENT

# =========================



@app.get("/admin/users")

def admin_get_users(

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db)

):

    users = db.query(User).order_by(User.id.asc()).all()



    return [

        {

            "id": user.id,

            "name": user.name,

            "email": user.email,

            "phone": decrypt_phone_number(user.phone),

            "wallet_balance": float(user.wallet_balance or 0),

            "created_at": user.created_at

        }

        for user in users

    ]





# =========================

# ADMIN TRANSACTION MANAGEMENT

# =========================



@app.get("/admin/transactions")

def admin_get_transactions(

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db)

):

    transactions = (

        db.query(WalletTransaction, User, Admin)

        .outerjoin(

            User,

            WalletTransaction.user_id == User.id

        )

        .outerjoin(

            Admin,

            WalletTransaction.admin_id == Admin.id

        )

        .order_by(

            WalletTransaction.created_at.desc(),

            WalletTransaction.id.desc()

        )

        .all()

    )



    return [

        {

            "transaction_id": transaction.id,

            "owner_type": (

                "customer" if transaction.user_id is not None

                else "admin" if transaction.admin_id is not None

                else "unknown"

            ),

            "user_id": user.id if user else None,

            "user_name": user.name if user else None,

            "user_phone": decrypt_phone_number(user.phone) if user else None,

            "user_email": user.email if user else None,

            "admin_id": admin.id if admin else None,

            "admin_username": admin.username if admin else None,

            "transaction_type": transaction.transaction_type,

            "amount": float(transaction.amount),

            "status": transaction.status,

            "reference": transaction.reference,

            "gateway": transaction.gateway,

            "created_at": transaction.created_at

        }

        for transaction, user, admin in transactions

    ]




@app.get("/admin/profit-report")
def admin_profit_report(
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    transactions = (
        db.query(WalletTransaction)
        .filter(
            WalletTransaction.status == "success",
            WalletTransaction.transaction_type.in_(
                ["airtime_purchase", "data_purchase"]
            ),
            WalletTransaction.gateway.in_(["ridamsub", "gndata"]),
        )
        .all()
    )

    report = {
        "total_transactions": len(transactions),
        "total_sales": Decimal("0.00"),
        "sales_with_known_cost": Decimal("0.00"),
        "total_provider_cost": Decimal("0.00"),
        "gross_profit": Decimal("0.00"),
        "unknown_cost_sales": Decimal("0.00"),
        "unknown_cost_transactions": 0,
        "providers": {},
        "services": {},
    }

    for tx in transactions:
        provider = tx.gateway
        service = (
            "airtime"
            if tx.transaction_type == "airtime_purchase"
            else "data"
        )

        amount = Decimal(str(tx.amount))

        report["total_sales"] += amount

        if provider not in report["providers"]:
            report["providers"][provider] = {
                "sales": Decimal("0.00"),
                "provider_cost": Decimal("0.00"),
                "gross_profit": Decimal("0.00"),
                "unknown_cost_sales": Decimal("0.00"),
                "unknown_cost_transactions": 0,
            }

        if service not in report["services"]:
            report["services"][service] = {
                "sales": Decimal("0.00"),
                "provider_cost": Decimal("0.00"),
                "gross_profit": Decimal("0.00"),
                "unknown_cost_sales": Decimal("0.00"),
            }

        provider_row = report["providers"][provider]
        service_row = report["services"][service]

        provider_row["sales"] += amount
        service_row["sales"] += amount

        if tx.provider_cost is None:
            report["unknown_cost_sales"] += amount
            report["unknown_cost_transactions"] += 1

            provider_row["unknown_cost_sales"] += amount
            provider_row["unknown_cost_transactions"] += 1

            continue

        cost = Decimal(str(tx.provider_cost))
        profit = amount - cost

        report["sales_with_known_cost"] += amount
        report["total_provider_cost"] += cost
        report["gross_profit"] += profit

        provider_row["provider_cost"] += cost
        provider_row["gross_profit"] += profit

        service_row["provider_cost"] += cost
        service_row["gross_profit"] += profit

    def serialize(value):
        if isinstance(value, Decimal):
            return float(value)

        if isinstance(value, dict):
            return {
                key: serialize(item)
                for key, item in value.items()
            }

        return value

    return serialize(report)




@app.get("/api/reconcile/{local_reference}")

def inspect_ridamsub_reconciliation(

    local_reference: str,

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db),

):

    """

    Inspect a local Ridamsub transaction for manual reconciliation.



    This endpoint does not contact Ridamsub, retry purchases,

    change transaction status, or issue refunds.

    """



    transaction = (

        db.query(WalletTransaction)

        .filter(

            WalletTransaction.reference == local_reference,

            WalletTransaction.gateway == "ridamsub",

        )

        .first()

    )



    if transaction is None:

        raise HTTPException(

            status_code=404,

            detail="Ridamsub transaction not found.",

        )



    return {

        "local_reference": transaction.reference,

        "transaction_id": transaction.id,

        "user_id": transaction.user_id,

        "transaction_type": transaction.transaction_type,

        "amount": str(transaction.amount),

        "status": transaction.status,

        "next_action": (

            "Verify the transaction in the Ridamsub provider panel "

            "or a confirmed provider transaction log. Do not retry "

            "or refund until the outcome is established."

            if transaction.status == "pending"

            else "Review the recorded transaction status."

        ),

    }







# =========================

# ADMIN AUDIT LOGS

# =========================



@app.get("/admin/audit-logs")

def admin_get_audit_logs(

    limit: int = Query(default=50, ge=1, le=200),

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db)

):

    logs = (

        db.query(AdminAuditLog)

        .order_by(

            AdminAuditLog.created_at.desc(),

            AdminAuditLog.id.desc()

        )

        .limit(limit)

        .all()

    )



    return [

        {

            "id": log.id,

            "action": log.action,

            "admin_id": log.admin_id,

            "reason": log.reason,

            "amount": (

                float(log.amount)

                if log.amount is not None

                else None

            ),

            "reference": log.reference,

            "created_at": log.created_at

        }

        for log in logs

    ]





# =========================

# PROTECTED USER PROFILE

# =========================

@app.get("/me")
def get_my_profile(
    current_user: User = Depends(get_current_user)
):
    return {
        "message": "Authenticated user",
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "phone": decrypt_phone_number(current_user.phone),
        "created_at": current_user.created_at
    }


@app.put("/profile")
def update_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    submitted_phone = request.phone.strip()
    phone_hash = hash_phone_number(submitted_phone)

    existing_phone = db.query(User).filter(
        User.id != current_user.id,
        (
            (User.phone_hash == phone_hash) |
            (
                (User.phone == submitted_phone) &
                (User.phone_hash.is_(None))
            )
        )
    ).first()

    if existing_phone:
        raise HTTPException(
            status_code=409,
            detail="This phone number is already in use."
        )

    current_user.name = request.name.strip()
    current_user.email = str(request.email).strip().lower()
    current_user.phone = encrypt_phone_number(submitted_phone)
    current_user.phone_hash = phone_hash

    db.commit()
    db.refresh(current_user)

    return {
        "message": "Profile updated successfully.",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "phone": decrypt_phone_number(current_user.phone)
        }
    }




@app.get("/wallet")

def get_wallet(

    current_user: User = Depends(get_current_user)

):

    return {

        "user_id": current_user.id,

        "balance": float(current_user.wallet_balance)

    }



# =========================

# APPROVED DATA PLAN CATALOGUE

# =========================



APPROVED_DATA_PLANS = {

    "mtn": {

        "mtn-50mb-200": {

            "name": "MTN 200MB â€” 2 days",

            "selling_price": 230,

        },

        "mtn-2-5gb-600": {

            "name": "MTN 2.5GB â€” 2 days",

            "selling_price": 680,

        },

        "mtn-3gb-1500": {

            "name": "MTN 3GB â€” 30 days",

            "selling_price": 1600,

        },

        "mtn-3gb-2500": {

            "name": "MTN 6GB â€” 30 days",

            "selling_price": 2750,

        },

        "mtn-data-3000": {

            "name": "MTN 8GB â€” 30 days",

            "selling_price": 3310,

        },

        "mtn-1gb-3500": {

            "name": "MTN 10GB â€” 30 days",

            "selling_price": 3740,

        },

        "mtn-100hr-5000": {

            "name": "MTN 15GB â€” 30 days",

            "selling_price": 5250,

        },

        "mtn-3gb-6000": {

            "name": "MTN 20GB â€” 30 days",

            "selling_price": 6300,

        },

        "mtn-40gb-10000": {

            "name": "MTN 40GB â€” 30 days",

            "selling_price": 10500,

        },

    }

}




async def get_live_gndata_plans(network_id: int):
    """
    Return approved GN plans that GN currently marks as available.
    Keep Omotech selling prices; refresh provider costs from GN.
    """
    client = GNDataClient()

    if not client.enabled or not client.api_key:
        raise HTTPException(
            status_code=503,
            detail="GN Data catalogue is unavailable.",
        )

    try:
        response = await client.data_services(include_plans=True)
    except GNDataError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not retrieve the live GN Data catalogue.",
        ) from exc

    if not isinstance(response, dict):
        raise HTTPException(
            status_code=503,
            detail="GN Data returned an invalid catalogue.",
        )

    services = response.get("data")

    if not isinstance(services, list):
        raise HTTPException(
            status_code=503,
            detail="GN Data catalogue format is invalid.",
        )

    service = next(
        (
            item for item in services
            if isinstance(item, dict)
            and str(item.get("id")) == str(network_id)
        ),
        None,
    )

    if service is None:
        return {}

    live_plans = service.get("plans")

    if not isinstance(live_plans, list):
        raise HTTPException(
            status_code=503,
            detail="GN Data plan catalogue is invalid.",
        )

    approved_plans = {}

    for live_plan in live_plans:
        if not isinstance(live_plan, dict):
            continue

        if live_plan.get("available") is not True:
            continue

        try:
            plan_id = int(live_plan["id"])
            provider_cost = Decimal(str(live_plan["price"]))
        except (KeyError, TypeError, ValueError):
            continue

        if not provider_cost.is_finite() or provider_cost <= 0:
            continue

        # Only sell plans with an approved Omotech selling price.
        configured = get_plan(plan_id, network_id=network_id)

        if configured is None:
            continue

        approved_plan = dict(configured)
        approved_plan["provider_cost"] = provider_cost.quantize(
            Decimal("0.01")
        )

        approved_plans[plan_id] = approved_plan

    return approved_plans





@app.get("/gndata/data/plans/{network}")
async def get_gndata_data_plans(network: str):
    network_key = network.strip().lower()

    network_info = GN_DATA_NETWORKS.get(network_key)

    if network_info is None:
        raise HTTPException(
            status_code=404,
            detail="Unsupported GN Data network.",
        )

    network_id = network_info["network_id"]
    plans = await get_live_gndata_plans(network_id)

    customer_plans = []

    for plan in plans:
        customer_plans.append({
            "variation_code": str(plan["plan_id"]),
            "plan_id": plan["plan_id"],
            "name": plan["name"],
            "price": str(plan["selling_price"]),
            "validity": plan.get("validity", "Not specified"),
            "type": plan.get("plan_type", "Data"),
        })

    return {
        "network": network_key,
        "network_id": network_id,
        "plans": customer_plans,
    }

@app.get("/data/plans/{network}")
async def get_data_plans(network: str):
    network_key = str(network).strip().lower()

    if network_key not in GN_DATA_NETWORKS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported network.",
        )

    plans = []
    seen_plan_ids = set()

    # GN Data plans take priority.
    gn_network = GN_DATA_NETWORKS[network_key]
    gn_network_id = int(gn_network["network_id"])

    live_gn_plans = await get_live_gndata_plans(gn_network_id)

    for plan in live_gn_plans.values():
        plans.append({
            "plan_id": plan["plan_id"],
            "name": plan["name"],
            "validity": plan["validity"],
            "plan_type": plan["plan_type"],
            "selling_price": float(plan["selling_price"]),
            "provider": "gndata",
        })
        seen_plan_ids.add(str(plan["plan_id"]))

    # Add Ridamsub plans not already supplied by GN Data.
    for plan in RIDAMSUB_DATA_PLANS.get(network_key, []):
        plan_id = str(plan.get("plan_id"))

        if plan_id in seen_plan_ids:
            continue

        if plan.get("available", True) is not True:
            continue

        plans.append({
            "plan_id": plan["plan_id"],
            "name": plan["name"],
            "validity": plan["validity"],
            "selling_price": float(Decimal(str(plan["selling_price"]))),
            "provider": "ridamsub",
        })
        seen_plan_ids.add(plan_id)

    return {
        "network": network_key,
        "plans": plans,
    }



def validate_idempotency_key(value: str | None) -> str:
    """Validate and normalize an incoming Idempotency-Key header."""

    if not isinstance(value, str):
        raise HTTPException(
            status_code=400,
            detail="An Idempotency-Key header is required.",
        )

    key = value.strip()

    if not key or len(key) > 100:
        raise HTTPException(
            status_code=400,
            detail="A valid Idempotency-Key is required.",
        )

    return key


@app.post("/data/purchase")
async def purchase_data(
    request: DataPurchaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key"
    ),
    background_tasks: BackgroundTasks = None,
):
    key = validate_idempotency_key(idempotency_key)

    try:
        plan_id = int(request.variation_code)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Invalid data plan ID."
        )

    return await execute_data_purchase(
        db=db,
        user_id=current_user.id,
        network=request.network,
        phone=request.phone,
        plan_id=plan_id,
        idempotency_key=key,
        background_tasks=background_tasks,
    )



@app.post("/airtime/purchase")

async def purchase_airtime(

    request: AirtimePurchaseRequest,

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db),

    idempotency_key: str | None = Header(

        default=None, alias="Idempotency-Key"

    ),

    background_tasks: BackgroundTasks = None,

):


    key = validate_idempotency_key(idempotency_key)

    network_key = str(request.network).strip().lower()
    gn_network = GN_DATA_NETWORKS.get(network_key)
    gn_client = GNDataClient()

    # GN Data gets first priority when enabled and configured.
    # No fallback is attempted after a GN purchase request is submitted.
    if (
        gn_network
        and gn_client.enabled
        and gn_client.api_key
    ):
        return await execute_gndata_airtime_purchase(
            db=db,
            user_id=current_user.id,
            network=request.network,
            phone=request.phone,
            amount=request.amount,
            idempotency_key=key,
            background_tasks=background_tasks,
        )

    # Ridamsub is used only when GN cannot be selected before submission.
    if not RIDAMSUB_PURCHASES_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="Airtime purchases are temporarily unavailable.",
        )

    return await execute_ridamsub_purchase(
        db=db,
        user_id=current_user.id,
        purchase_type="airtime",
        network=request.network,
        phone=request.phone,
        amount=request.amount,
        idempotency_key=key,
        background_tasks=background_tasks,
    )






@app.post("/wallet/fund")

def fund_wallet(

    request: FundWalletRequest,

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db)

):

    if not PAYSTACK_SECRET_KEY:

        raise HTTPException(

            status_code=500,

            detail="Payment service is not configured."

        )



    reference = secrets.token_urlsafe(24)

    transaction = WalletTransaction(

        user_id=current_user.id,

        transaction_type="funding",

        amount=request.amount,

        status="pending",

        reference=reference,

        gateway="paystack"

    )



    db.add(transaction)

    db.commit()

    db.refresh(transaction)



    try:

        response = requests.post(

            "https://api.paystack.co/transaction/initialize",

            headers={

                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",

                "Content-Type": "application/json"

            },

            json={

                "email": current_user.email,

                "amount": int(request.amount * 100),

                "reference": reference,

                "metadata": {

                    "user_id": current_user.id,

                    "transaction_id": transaction.id

                }

            },

            timeout=30

        )



        result = response.json()



        if not response.ok or not result.get("status"):

            transaction.status = "failed"

            db.commit()

            raise HTTPException(

                status_code=502,

                detail="Unable to initialize Paystack payment."

            )



        return {

            "message": "Payment initialized successfully.",

            "transaction_id": transaction.id,

            "reference": reference,

            "status": "pending",

            "authorization_url": result["data"]["authorization_url"]

        }



    except requests.RequestException:

        transaction.status = "failed"

        db.commit()

        raise HTTPException(

            status_code=502,

            detail="Unable to connect to the payment service."

        )





@app.post("/wallet/verify/{reference}")

def verify_wallet_funding(

    reference: str,

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db)

):

    try:

        # Lock the funding transaction to prevent duplicate credits.

        transaction = db.query(WalletTransaction).filter(

            WalletTransaction.reference == reference,

            WalletTransaction.user_id == current_user.id,

            WalletTransaction.transaction_type == "funding"

        ).with_for_update().first()



        if not transaction:

            db.rollback()

            raise HTTPException(

                status_code=404,

                detail="Funding transaction not found."

            )





        if transaction.gateway != "paystack":

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="This transaction does not belong to Paystack."

            )



        if transaction.status == "success":

            balance = db.query(User.wallet_balance).filter(

                User.id == current_user.id

            ).scalar()



            db.commit()



            return {

                "message": "Payment already verified.",

                "status": "success",

                "wallet_balance": float(balance)

            }



        if transaction.status != "pending":

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="This transaction cannot be verified."

            )



        # Verify the payment directly with Paystack.

        response = requests.get(

            f"https://api.paystack.co/transaction/verify/{reference}",

            headers={

                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"

            },

            timeout=30

        )



        result = response.json()



        if not response.ok or not result.get("status"):

            db.rollback()

            raise HTTPException(

                status_code=502,

                detail="Paystack verification request failed."

            )



        payment = result.get("data", {})



        if payment.get("status") != "success":

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="Paystack has not confirmed a successful payment."

            )



        if payment.get("reference") != transaction.reference:

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="Payment reference mismatch."

            )



        expected_kobo = int(transaction.amount * 100)



        if payment.get("amount") != expected_kobo:

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="Payment amount does not match."

            )



        if payment.get("currency") != "NGN":

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="Payment currency does not match."

            )



        # Lock the user's database row before updating the balance.

        user = db.query(User).filter(

            User.id == current_user.id

        ).with_for_update().first()



        if not user or not user.email:

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="A valid user email is required."

            )



        customer_email = (

            payment.get("customer", {}).get("email", "").strip().lower()

        )



        if customer_email != user.email.strip().lower():

            db.rollback()

            raise HTTPException(

                status_code=400,

                detail="Payment email does not match the user's email."

            )



        # Credit the wallet and mark the transaction in one commit.

        user.wallet_balance += transaction.amount

        transaction.status = "success"



        db.commit()

        db.refresh(user)



        return {

            "message": "Wallet funded successfully.",

            "status": "success",

            "amount": float(transaction.amount),

            "wallet_balance": float(user.wallet_balance)

        }



    except HTTPException:

        raise

    except requests.RequestException:

        db.rollback()

        raise HTTPException(

            status_code=502,

            detail="Unable to contact Paystack."

        )

    except Exception:

        db.rollback()

        raise HTTPException(

            status_code=500,

            detail="Wallet verification failed. Please retry."

        )





# =========================

# PAYSTACK WEBHOOK

# =========================

@app.post("/payments/paystack/webhook")

@app.post("/paystack/webhook")

async def paystack_webhook(

    request: Request,

    db: Session = Depends(get_db)

):

    if not PAYSTACK_SECRET_KEY:

        raise HTTPException(

            status_code=500,

            detail="Payment service is not configured."

        )



    # 1. Verify the signature using the original request body.

    body = await request.body()

    signature = request.headers.get("x-paystack-signature", "")



    expected_signature = hmac.new(

        PAYSTACK_SECRET_KEY.encode("utf-8"),

        body,

        hashlib.sha512

    ).hexdigest()



    if not signature or not hmac.compare_digest(

        signature, expected_signature

    ):

        raise HTTPException(

            status_code=401,

            detail="Invalid Paystack webhook signature."

        )



    # 2. Parse the webhook event.

    try:

        event_data = json.loads(body)

    except (json.JSONDecodeError, UnicodeDecodeError):

        raise HTTPException(

            status_code=400,

            detail="Invalid webhook payload."

        )



    if event_data.get("event") != "charge.success":

        return {"status": "received"}



    event_payment = event_data.get("data") or {}

    reference = event_payment.get("reference")



    if not reference:

        raise HTTPException(

            status_code=400,

            detail="Payment reference is missing."

        )



    # 3. Verify the transaction independently with Paystack.

    try:

        response = requests.get(

            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",

            headers={

                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"

            },

            timeout=30

        )

        response.raise_for_status()

        result = response.json()



    except requests.Timeout:

        raise HTTPException(

            status_code=504,

            detail="Paystack verification timed out."

        )

    except requests.RequestException:

        raise HTTPException(

            status_code=502,

            detail="Unable to contact Paystack."

        )

    except ValueError:

        raise HTTPException(

            status_code=502,

            detail="Invalid response from Paystack."

        )



    if not result.get("status"):

        raise HTTPException(

            status_code=502,

            detail="Paystack could not verify the payment."

        )



    payment = result.get("data") or {}



    if (

        payment.get("status") != "success"

        or payment.get("reference") != reference

        or event_payment.get("reference") != reference

    ):

        raise HTTPException(

            status_code=400,

            detail="Payment verification failed."

        )



    if payment.get("currency") != "NGN":

        raise HTTPException(

            status_code=400,

            detail="Payment currency does not match."

        )



    # 4. Find and lock the funding transaction.

    try:

        transaction = (

            db.query(WalletTransaction)

            .filter(

                WalletTransaction.reference == reference,

                WalletTransaction.transaction_type == "funding",

                WalletTransaction.gateway == "paystack"

            )

            .with_for_update()

            .first()

        )



        if not transaction:

            raise HTTPException(

                status_code=404,

                detail="Funding transaction not found."

            )



        # A transaction must belong to exactly one account.

        is_customer_transaction = transaction.user_id is not None

        is_admin_transaction = transaction.admin_id is not None



        if is_customer_transaction == is_admin_transaction:

            raise HTTPException(

                status_code=400,

                detail="Transaction ownership is invalid."

            )



        # Ignore duplicate webhook deliveries.

        if transaction.status == "success":

            db.rollback()

            return {"status": "received"}



        if transaction.status != "pending":

            db.rollback()

            return {"status": "received"}



        # 5. Validate the amount against the pending transaction.

        expected_kobo = int(

            Decimal(str(transaction.amount)) * Decimal("100")

        )



        if payment.get("amount") != expected_kobo:

            raise HTTPException(

                status_code=400,

                detail="Payment amount does not match."

            )



        customer_email = (

            (payment.get("customer") or {}).get("email") or ""

        ).strip().lower()



        # 6. Credit the correct wallet.

        if is_customer_transaction:

            user = (

                db.query(User)

                .filter(User.id == transaction.user_id)

                .with_for_update()

                .first()

            )



            if not user or not user.email:

                raise HTTPException(

                    status_code=400,

                    detail="Funding user or email not found."

                )



            if customer_email != user.email.strip().lower():

                raise HTTPException(

                    status_code=400,

                    detail="Payment email does not match."

                )



            user.wallet_balance += transaction.amount



        else:

            admin = (

                db.query(Admin)

                .filter(Admin.id == transaction.admin_id)

                .with_for_update()

                .first()

            )



            if not admin or not admin.email:

                raise HTTPException(

                    status_code=400,

                    detail="Funding admin or email not found."

                )



            if customer_email != admin.email.strip().lower():

                raise HTTPException(

                    status_code=400,

                    detail="Payment email does not match."

                )



            admin.wallet_balance += transaction.amount



            db.add(

                AdminAuditLog(

                    admin_id=admin.id,

                    user_id=None,

                    action="admin_wallet_funding_completed",

                    amount=transaction.amount,

                    reason="Paystack webhook verified admin funding",

                    reference=reference

                )

            )



        # Commit wallet credit and transaction status together.

        transaction.status = "success"

        db.commit()



        return {"status": "received"}



    except HTTPException:

        db.rollback()

        raise

    except Exception:

        db.rollback()

        raise HTTPException(

            status_code=500,

            detail="Unable to process Paystack webhook."

        )







@app.get("/transactions")

def get_transactions(

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db)

):

    transactions = (

        db.query(WalletTransaction)

        .filter(WalletTransaction.user_id == current_user.id)

        .order_by(WalletTransaction.id.desc())

        .all()

    )



    return {

        "user_id": current_user.id,

        "transactions": [

            {

                "transaction_id": transaction.id,

                "transaction_type": transaction.transaction_type,

                "amount": float(transaction.amount),

                "status": transaction.status,

                "reference": transaction.reference,

                "gateway": transaction.gateway



            }

            for transaction in transactions

        ]

    }





# =========================

# ADMIN DASHBOARD OVERVIEW

# =========================



@app.get("/admin/overview")

def admin_overview(

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db)

):

    total_users = db.query(func.count(User.id)).scalar() or 0



    total_admins = db.query(

        func.count(Admin.id)

    ).filter(

        Admin.is_active == True

    ).scalar() or 0



    total_transactions = db.query(

        func.count(WalletTransaction.id)

    ).filter(

        WalletTransaction.transaction_type == "funding"

    ).scalar() or 0



    successful_transactions = db.query(

        func.count(WalletTransaction.id)

    ).filter(

        WalletTransaction.transaction_type == "funding",

        WalletTransaction.status == "success"

    ).scalar() or 0



    pending_transactions = db.query(

        func.count(WalletTransaction.id)

    ).filter(

        WalletTransaction.transaction_type == "funding",

        WalletTransaction.status == "pending"

    ).scalar() or 0



    total_wallet_balance = db.query(

        func.coalesce(func.sum(User.wallet_balance), 0)

    ).scalar()



    return {

        "admin": current_admin.username,

        "overview": {

            "total_users": total_users,

            "active_admins": total_admins,

            "total_funding_transactions": total_transactions,

            "successful_transactions": successful_transactions,

            "pending_transactions": pending_transactions,

            "total_wallet_balance": float(total_wallet_balance)

        }

    }



@app.post("/paystack/initialize")

def initialize_paystack_payment(

    request: FundWalletRequest,

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db)

):

    # Check payment configuration.

    if not PAYSTACK_SECRET_KEY:

        raise HTTPException(

            status_code=503,

            detail="Payment service is not configured."

        )



    # Paystack requires an email address.

    if not current_user.email or not current_user.email.strip():

        raise HTTPException(

            status_code=400,

            detail="Please add an email address to your profile before funding your wallet."

        )



    # Reject amounts that cannot be represented exactly in kobo.

    if request.amount != request.amount.quantize(Decimal("0.01")):

        raise HTTPException(

            status_code=400,

            detail="Amount must have no more than two decimal places."

        )



    reference = secrets.token_urlsafe(24)



    # Save the pending transaction before contacting Paystack.

    transaction = WalletTransaction(

        user_id=current_user.id,

        transaction_type="funding",

        amount=request.amount,

        status="pending",

        reference=reference,

        gateway="paystack"

    )



    try:

        db.add(transaction)

        db.commit()

        db.refresh(transaction)

    except Exception:

        db.rollback()

        raise HTTPException(

            status_code=500,

            detail="Unable to create the payment transaction."

        )



    payload = {

        "email": current_user.email.strip(),

        "amount": int(request.amount * Decimal("100")),

        "reference": reference,

       "callback_url": (

    "https://omotech.com.ng/payment-success"

),

    }



    headers = {

        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",

        "Content-Type": "application/json"

    }



    try:

        response = requests.post(

            f"{PAYSTACK_BASE_URL}/transaction/initialize",

            json=payload,

            headers=headers,

            timeout=15

        )



        try:

            data = response.json()

        except ValueError:

            # Keep the transaction pending because the outcome is uncertain.

            raise HTTPException(

                status_code=502,

                detail="Paystack returned an invalid response. Check the transaction status before retrying."

            )



        if not response.ok or not data.get("status"):

            transaction.status = "failed"

            db.commit()



            raise HTTPException(

                status_code=502,

                detail=data.get(

                    "message",

                    "Unable to initialize payment."

                )

            )



        payment_data = data.get("data", {})



        if (

            payment_data.get("reference") != reference

            or not payment_data.get("authorization_url")

        ):

            raise HTTPException(

                status_code=502,

                detail="Paystack returned incomplete payment details. Check the transaction status before retrying."

            )



        return {

            "authorization_url": payment_data["authorization_url"],

            "reference": reference,

            "amount": float(transaction.amount),

            "status": transaction.status

        }



    except requests.Timeout:

        # Do not mark failed: Paystack may have initialized the payment

        # even though the response timed out.

        raise HTTPException(

            status_code=504,

            detail="Paystack timed out. Check your transaction history before trying again."

        )



    except requests.RequestException:

        # The result may be uncertain, so retain the pending transaction.

        raise HTTPException(

            status_code=502,

            detail="Unable to contact Paystack. Check your transaction history before trying again."

        )



    except HTTPException:

        raise



    except Exception:

        db.rollback()

        raise HTTPException(

            status_code=500,

            detail="An unexpected error occurred while initializing payment."

        )





@app.get("/payment-success")

def payment_success(reference: str):

    return FileResponse("payment-success.html")





@app.post("/admin/wallet/verify/{reference}")

def verify_admin_wallet_funding(

    reference: str,

    current_admin: Admin = Depends(get_current_admin),

    db: Session = Depends(get_db)

):

    if not PAYSTACK_SECRET_KEY:

        raise HTTPException(

            status_code=503,

            detail="Payment service is not configured."

        )



    try:

        response = requests.get(

            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",

            headers={

                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"

            },

            timeout=15

        )

        response.raise_for_status()

        result = response.json()



    except requests.Timeout:

        raise HTTPException(

            status_code=504,

            detail="Paystack verification timed out. Please try again."

        )

    except (requests.RequestException, ValueError):

        raise HTTPException(

            status_code=502,

            detail="Unable to verify payment with Paystack."

        )



    payment = result.get("data") or {}



    if not result.get("status"):

        raise HTTPException(

            status_code=502,

            detail="Paystack could not verify the payment."

        )



    if payment.get("status") != "success":

        return {

            "message": "Payment has not been completed.",

            "status": payment.get("status"),

            "reference": reference

        }



    if payment.get("reference") != reference:

        raise HTTPException(

            status_code=400,

            detail="Payment reference mismatch."

        )



    if payment.get("currency") != "NGN":

        raise HTTPException(

            status_code=400,

            detail="Payment currency is not supported."

        )



    payment_email = (

        (payment.get("customer") or {}).get("email") or ""

    ).strip().lower()



    admin_email = (current_admin.email or "").strip().lower()



    if not admin_email or payment_email != admin_email:

        raise HTTPException(

            status_code=400,

            detail="Payment email does not match the admin account."

        )



    try:

        transaction = (

            db.query(WalletTransaction)

            .filter(

                WalletTransaction.reference == reference,

                WalletTransaction.admin_id == current_admin.id,

                WalletTransaction.user_id.is_(None)

            )

            .with_for_update()

            .first()

        )



        if not transaction:

            raise HTTPException(

                status_code=404,

                detail="Admin funding transaction not found."

            )



        if (

            transaction.transaction_type != "funding"

            or transaction.gateway != "paystack"

        ):

            raise HTTPException(

                status_code=400,

                detail="This is not a valid admin funding transaction."

            )



        if transaction.status == "success":

            return {

                "message": "Payment has already been credited.",

                "status": "success",

                "reference": reference,

                "amount": float(transaction.amount),

                "wallet_balance": float(current_admin.wallet_balance)

            }



        if transaction.status != "pending":

            raise HTTPException(

                status_code=400,

                detail="This transaction cannot be credited."

            )



        paystack_amount = (

            Decimal(str(payment.get("amount", 0)))

            / Decimal("100")

        )



        if paystack_amount != Decimal(str(transaction.amount)):

            raise HTTPException(

                status_code=400,

                detail="Payment amount does not match the transaction."

            )



        db.execute(

            update(Admin)

            .where(Admin.id == current_admin.id)

            .values(

                wallet_balance=(

                    Admin.wallet_balance + transaction.amount

                )

            )

        )



        transaction.status = "success"



        db.add(

            AdminAuditLog(

                admin_id=current_admin.id,

                user_id=None,

                action="admin_wallet_funding_completed",

                amount=transaction.amount,

                reason="Paystack funding verified successfully",

                reference=reference

            )

        )



        db.commit()

        db.refresh(current_admin)

        db.refresh(transaction)



        return {

            "message": "Admin wallet funded successfully.",

            "status": transaction.status,

            "reference": transaction.reference,

            "amount": float(transaction.amount),

            "wallet_balance": float(current_admin.wallet_balance)

        }



    except HTTPException:

        db.rollback()

        raise

    except Exception:

        db.rollback()

        raise HTTPException(

            status_code=500,

            detail="Unable to process admin payment verification."

        )

@app.post("/admin/wallet/reconcile-customer/{reference}")
def reconcile_customer_paystack_funding(
    reference: str,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service is not configured."
        )

    # Verify the payment directly with Paystack.
    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
            },
            timeout=15
        )
        response.raise_for_status()
        result = response.json()

    except requests.Timeout:
        raise HTTPException(
            status_code=504,
            detail="Paystack verification timed out."
        )
    except (requests.RequestException, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Unable to verify payment with Paystack."
        )

    payment = result.get("data") or {}

    if not result.get("status"):
        raise HTTPException(
            status_code=502,
            detail="Paystack could not verify the payment."
        )

    if payment.get("status") != "success":
        return {
            "status": payment.get("status"),
            "message": "Paystack has not confirmed successful payment."
        }

    if payment.get("reference") != reference:
        raise HTTPException(
            status_code=400,
            detail="Payment reference mismatch."
        )

    if payment.get("currency") != "NGN":
        raise HTTPException(
            status_code=400,
            detail="Unsupported payment currency."
        )

    try:
        paystack_amount = (
            Decimal(str(payment.get("amount", 0)))
            / Decimal("100")
        )

        if paystack_amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid payment amount."
            )

        transaction = (
            db.query(WalletTransaction)
            .filter(
                WalletTransaction.reference == reference,
                WalletTransaction.gateway == "paystack",
                WalletTransaction.transaction_type == "funding",
                WalletTransaction.user_id.isnot(None),
                WalletTransaction.admin_id.is_(None)
            )
            .with_for_update()
            .first()
        )

        if not transaction:
            raise HTTPException(
                status_code=404,
                detail="Customer Paystack funding transaction not found."
            )

        if transaction.status == "success":
            return {
                "status": "success",
                "message": "Payment has already been credited.",
                "reference": reference,
                "amount": float(transaction.amount)
            }

        if transaction.status != "pending":
            raise HTTPException(
                status_code=400,
                detail="Transaction is not eligible for reconciliation."
            )

        if paystack_amount != Decimal(str(transaction.amount)):
            raise HTTPException(
                status_code=400,
                detail="Paystack amount does not match the local transaction."
            )

        user = (
            db.query(User)
            .filter(User.id == transaction.user_id)
            .with_for_update()
            .first()
        )

        if not user or not user.email:
            raise HTTPException(
                status_code=400,
                detail="Customer account or email not found."
            )

        payment_email = (
            (payment.get("customer") or {}).get("email") or ""
        ).strip().lower()

        if payment_email != user.email.strip().lower():
            raise HTTPException(
                status_code=400,
                detail="Paystack email does not match the customer account."
            )

        # Credit only the verified customer's wallet.
        user.wallet_balance = (
            Decimal(str(user.wallet_balance))
            + Decimal(str(transaction.amount))
        )

        transaction.status = "success"

        db.add(
            AdminAuditLog(
                admin_id=current_admin.id,
                user_id=user.id,
                action="customer_funding_reconciled",
                amount=transaction.amount,
                reason=f"Admin verified Paystack funding: {reference}",
                reference=reference
            )
        )

        db.commit()
        db.refresh(transaction)
        db.refresh(user)

        return {
            "status": "success",
            "message": "Customer wallet successfully reconciled.",
            "reference": transaction.reference,
            "user_id": user.id,
            "amount": float(transaction.amount),
            "wallet_balance": float(user.wallet_balance)
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception(
            "Customer Paystack reconciliation failed for %s",
            reference
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to reconcile customer payment."

        )



@app.post("/admin/providers/gndata/reconcile/{reference}")
async def reconcile_gndata_purchase(
    reference: str,
    request: Request,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """
    Manually reconcile an existing GN Data purchase using confirmed
    provider evidence. This endpoint never changes the customer's wallet.
    """
    reference = str(reference or "").strip()

    if not reference:
        raise HTTPException(status_code=400, detail="Transaction reference is required.")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid reconciliation details.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid reconciliation details.")

    provider_transaction_id = str(
        payload.get("provider_transaction_id") or ""
    ).strip()

    if not provider_transaction_id or len(provider_transaction_id) > 100:
        raise HTTPException(
            status_code=400,
            detail="A valid GN Data provider transaction reference is required.",
        )

    try:
        provider_cost = Decimal(str(payload.get("provider_cost", "")))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid provider cost.")

    if not provider_cost.is_finite() or provider_cost <= 0:
        raise HTTPException(
            status_code=400,
            detail="Provider cost must be a positive amount.",
        )

    if provider_cost > Decimal("9999999999.99"):
        raise HTTPException(
            status_code=400,
            detail="Provider cost exceeds the permitted amount.",
        )

    if provider_cost.as_tuple().exponent < -2:
        raise HTTPException(
            status_code=400,
            detail="Provider cost must have no more than two decimal places.",
        )

    try:
        transaction = (
            db.query(WalletTransaction)
            .filter(
                WalletTransaction.reference == reference,
                WalletTransaction.gateway == "gndata",
                WalletTransaction.transaction_type.in_(
                    ["airtime_purchase", "data_purchase"]
                ),
                WalletTransaction.user_id.isnot(None),
                WalletTransaction.admin_id.is_(None),
            )
            .with_for_update()
            .first()
        )

        if not transaction:
            raise HTTPException(
                status_code=404,
                detail="Matching GN Data customer purchase was not found.",
            )

        current_status = str(transaction.status or "").strip().lower()

        if current_status == "success":
            same_provider_reference = (
                str(transaction.provider_transaction_id or "").strip()
                == provider_transaction_id
            )
            same_provider_cost = (
                transaction.provider_cost is not None
                and Decimal(str(transaction.provider_cost)) == provider_cost
            )

            if same_provider_reference and same_provider_cost:
                return {
                    "status": "success",
                    "message": "This GN Data transaction has already been reconciled.",
                    "reference": transaction.reference,
                    "provider_transaction_id": transaction.provider_transaction_id,
                    "provider_cost": float(transaction.provider_cost),
                }

            raise HTTPException(
                status_code=409,
                detail="This transaction is already successful with different provider details.",
            )

        if current_status not in ("pending", "pending_requery"):
            raise HTTPException(
                status_code=409,
                detail=f"Transaction cannot be reconciled from status: {transaction.status}.",
            )

        existing_provider_reference = str(
            transaction.provider_transaction_id or ""
        ).strip()

        if (
            existing_provider_reference
            and existing_provider_reference != provider_transaction_id
        ):
            raise HTTPException(
                status_code=409,
                detail="A different provider transaction reference is already recorded.",
            )

        audit_reference = (
            "gndata-reconcile:"
            + hashlib.sha256(reference.encode("utf-8")).hexdigest()[:32]
        )

        transaction.provider_transaction_id = provider_transaction_id
        transaction.provider_cost = provider_cost
        transaction.status = "success"

        existing_audit = (
            db.query(AdminAuditLog)
            .filter(AdminAuditLog.reference == audit_reference)
            .first()
        )

        if not existing_audit:
            db.add(
                AdminAuditLog(
                    admin_id=current_admin.id,
                    user_id=transaction.user_id,
                    action="gndata_purchase_reconciled",
                    amount=transaction.amount,
                    reason=(
                        f"GN Data purchase manually reconciled. "
                        f"Local ref: {reference}; "
                        f"Provider ref: {provider_transaction_id}; "
                        f"Provider cost: {provider_cost}"
                    )[:255],
                    reference=audit_reference,
                )
            )

        db.commit()
        db.refresh(transaction)

        return {
            "status": "success",
            "message": "GN Data purchase successfully reconciled. Customer wallet was not changed.",
            "reference": transaction.reference,
            "provider_transaction_id": transaction.provider_transaction_id,
            "amount": float(transaction.amount),
            "provider_cost": float(transaction.provider_cost),
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception(
            "GN Data manual reconciliation failed for %s",
            reference,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to reconcile GN Data purchase.",
        )




@app.get("/paystack/verify/{reference}")

def verify_paystack_payment(

    reference: str,

    current_user: User = Depends(get_current_user),

    db: Session = Depends(get_db)

):

    if not PAYSTACK_SECRET_KEY:

        raise HTTPException(

            status_code=503,

            detail="Payment service is not configured."

        )



    try:

        response = requests.get(

            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",

            headers={

                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"

            },

            timeout=15

        )

        response.raise_for_status()

        data = response.json()



    except requests.Timeout:

        raise HTTPException(

            status_code=504,

            detail="Paystack verification timed out. Please try again."

        )

    except requests.RequestException:

        raise HTTPException(

            status_code=502,

            detail="Unable to contact Paystack."

        )

    except ValueError:

        raise HTTPException(

            status_code=502,

            detail="Paystack returned an invalid response."

        )



    if not data.get("status"):

        raise HTTPException(

            status_code=502,

            detail="Paystack could not verify the payment."

        )



    payment_data = data.get("data") or {}



    if payment_data.get("status") != "success":

        return {

            "message": "Payment has not been completed.",

            "status": payment_data.get("status"),

            "reference": reference

        }



    if payment_data.get("reference") != reference:

        raise HTTPException(

            status_code=400,

            detail="Payment reference mismatch."

        )



    if payment_data.get("currency") != "NGN":

        raise HTTPException(

            status_code=400,

            detail="Payment currency is not supported."

        )



    if not current_user.email or not current_user.email.strip():

        raise HTTPException(

            status_code=400,

            detail="Please add an email address to your profile."

        )



    customer_email = (

        (payment_data.get("customer") or {}).get("email") or ""

    ).strip().lower()



    if customer_email != current_user.email.strip().lower():

        raise HTTPException(

            status_code=400,

            detail="Payment email does not match your account."

        )



    try:

        transaction = (

            db.query(WalletTransaction)

            .filter(

                WalletTransaction.reference == reference,

                WalletTransaction.user_id == current_user.id

            )

            .with_for_update()

            .first()

        )



        if not transaction:

            raise HTTPException(

                status_code=404,

                detail="Wallet transaction not found."

            )



        if (

            transaction.transaction_type != "funding"

            or transaction.gateway != "paystack"

        ):

            raise HTTPException(

                status_code=400,

                detail="This is not a valid Paystack funding transaction."

            )



        if transaction.status == "success":

            db.commit()

            return {

                "message": "Payment has already been credited.",

                "status": "success",

                "reference": reference,

                "amount": float(transaction.amount)

            }



        if transaction.status != "pending":

            raise HTTPException(

                status_code=400,

                detail="This transaction cannot be credited."

            )



        paystack_amount = (

            Decimal(str(payment_data.get("amount", 0)))

            / Decimal("100")

        )

        transaction_amount = Decimal(str(transaction.amount))



        if transaction_amount != paystack_amount:

            raise HTTPException(

                status_code=400,

                detail="Payment amount does not match the wallet transaction."

            )



        result = db.execute(

            update(User)

            .where(User.id == transaction.user_id)

            .values(

                wallet_balance=User.wallet_balance + transaction.amount

            )

        )



        if result.rowcount != 1:

            raise HTTPException(

                status_code=404,

                detail="Wallet owner not found."

            )



        transaction.status = "success"

        db.commit()



        db.refresh(current_user)

        db.refresh(transaction)



        return {

            "message": "Payment verified and wallet credited successfully.",

            "status": transaction.status,

            "reference": transaction.reference,

            "amount": float(transaction.amount),

            "wallet_balance": float(current_user.wallet_balance)

        }



    except HTTPException:

        db.rollback()

        raise

    except Exception:

        db.rollback()

        raise HTTPException(

            status_code=500,

            detail="Unable to process payment verification."

        )





# =========================

# SERVE FRONTEND

# =========================



@app.get("/app")

def serve_app():



    return FileResponse("index.html")





@app.get("/admin-login.html", response_class=FileResponse)

def serve_admin_login():

    return FileResponse("admin-login.html")







@app.get("/admin-dashboard.html", response_class=FileResponse)

def serve_admin_dashboard():

    return FileResponse("admin-dashboard.html")
