
import os

import secrets

import hashlib

import hmac

import json

import requests

from decimal import Decimal

from datetime import datetime, timedelta, timezone

import jwt

from dotenv import load_dotenv

from fastapi import Depends, FastAPI, HTTPException, Request

from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from fastapi.responses import FileResponse

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


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
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
        String(20),
        unique=True,
        nullable=False,
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
        String,
        nullable=False,
        index=True
    )

    amount = Column(
        Numeric,
        nullable=True
    )

    reason = Column(
        String,
        nullable=True
    )

    reference = Column(
        String,
        nullable=True,
        index=True
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
    user_id = Column(Integer, nullable=False)
    transaction_type = Column(String(20), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    reference = Column(String(100), unique=True, nullable=False)
    gateway = Column(String(20), nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp()
    )


# Make sure required tables exist
Base.metadata.create_all(bind=engine)

# =========================
# FASTAPI APP
# =========================

app = FastAPI(
    title="Omotech Airtime & Data API",
    description="Backend API for the Omotech Airtime & Data application",
    version="1.0.0"
)


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

    return {
        "message": "Welcome to the Omotech Airtime & Data API"
    }


# =========================
# CREATE USER
# =========================

@app.post("/user")
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):

    existing_user = db.query(User).filter(
        User.phone == user_data.phone
    ).first()

    if existing_user:

        raise HTTPException(
            status_code=400,
            detail="Phone number already registered"
        )

    hashed_password = password_hash.hash(
        user_data.password
    )

    new_user = User(
        name=user_data.name,
        phone=user_data.phone,
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
        "phone": new_user.phone,
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

    user = db.query(User).filter(
        User.phone == login_data.phone
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

    access_token = create_access_token(
        user.id
    )

    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "id": user.id,
        "name": user.name,
        "phone": user.phone
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



    try:
        db.add(
            AdminAuditLog(
                admin_id=admin.id,
                action="admin_login",
                reason="Admin logged in successfully."
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print("ADMIN LOGIN AUDIT ERROR:", repr(e))
        # Allow login to succeed even if audit logging fails.
        pass


    return {
        "message": "Admin login successful.",
        "access_token": access_token,
        "token_type": "bearer",
        "admin": {
            "id": admin.id,
            "username": admin.username
        }
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

    user = db.query(User).filter(
        User.phone == request.phone
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

    user = db.query(User).filter(
        User.id == reset_record.user_id,
        User.phone == request.phone
    ).first()

    if not user:

        raise HTTPException(
            status_code=400,
            detail="Invalid password reset request"
        )

    user.password_hash = password_hash.hash(
        request.new_password
    )

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
            "phone": user.phone,
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
            "phone": user.phone,
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
        db.query(WalletTransaction, User)
        .join(
            User,
            WalletTransaction.user_id == User.id
        )
        .order_by(WalletTransaction.created_at.desc())
        .all()
    )

    return [
        {
            "transaction_id": transaction.id,
            "user_id": user.id,
            "user_name": user.name,
            "user_phone": user.phone,
            "user_email": user.email,
            "transaction_type": transaction.transaction_type,
            "amount": float(transaction.amount),
            "status": transaction.status,
            "reference": transaction.reference,
            "created_at": transaction.created_at
        }
        for transaction, user in transactions
    ]


# =========================
# ADMIN AUDIT LOGS
# =========================

@app.get("/admin/audit-logs")
def get_admin_audit_logs(
    limit: int = 50,
    current_admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    limit = max(1, min(limit, 100))

    logs = (
        db.query(AdminAuditLog)
        .order_by(
            AdminAuditLog.created_at.desc(),
            AdminAuditLog.id.desc()
        )
        .limit(limit)
        .all()
    )

    return {
        "status": "success",
        "count": len(logs),
        "audit_logs": [
            {
                "id": log.id,
                "admin_id": log.admin_id,
                "user_id": log.user_id,
                "action": log.action,
                "amount": (
                    float(log.amount)
                    if log.amount is not None
                    else None
                ),
                "reason": log.reason,
                "reference": log.reference,
                "created_at": log.created_at
            }
            for log in logs
        ]
    }




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
        "phone": current_user.phone,
        "created_at": current_user.created_at
    }

@app.put("/profile")
def update_profile(
    request: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    existing_phone = db.query(User).filter(
        User.phone == request.phone,
        User.id != current_user.id
    ).first()

    if existing_phone:
        raise HTTPException(
            status_code=409,
            detail="This phone number is already in use."
        )

    current_user.name = request.name.strip()
    current_user.email = str(request.email).strip().lower()
    current_user.phone = request.phone.strip()

    db.commit()
    db.refresh(current_user)

    return {
        "message": "Profile updated successfully.",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "phone": current_user.phone
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
async def paystack_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Payment service is not configured."
        )

    # 1. Verify the webhook signature using the raw request body.
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

    # 2. Parse the event.
    try:
        event_data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook payload."
        )

    # We only process successful payments here.
    if event_data.get("event") != "charge.success":
        return {"status": "received"}

    event_payment = event_data.get("data") or {}
    reference = event_payment.get("reference")

    if not reference:
        raise HTTPException(
            status_code=400,
            detail="Payment reference is missing."
        )

    try:
        # 3. Independently verify the payment with Paystack.
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
            },
            timeout=30
        )

        if not response.ok:
            raise HTTPException(
                status_code=502,
                detail="Paystack verification request failed."
            )

        result = response.json()

        if not result.get("status"):
            raise HTTPException(
                status_code=502,
                detail="Paystack could not verify the payment."
            )

        payment = result.get("data") or {}

    except requests.RequestException:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Unable to contact Paystack."
        )
    except ValueError:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Invalid response from Paystack."
        )

    # 4. Confirm the verified payment details.
    if (
        payment.get("status") != "success"
        or payment.get("reference") != reference
        or event_payment.get("reference") != reference
    ):
        raise HTTPException(
            status_code=400,
            detail="Payment verification failed."
        )

    # 5. Lock the transaction to prevent duplicate credits.
    try:
        transaction = db.query(WalletTransaction).filter(
            WalletTransaction.reference == reference,
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
            return {"status": "received"}


        # Paystack may send the same webhook more than once.
        if transaction.status == "success":
            db.commit()
            return {"status": "received"}

        if transaction.status != "pending":
            db.rollback()
            return {"status": "received"}

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

        user = db.query(User).filter(
            User.id == transaction.user_id
        ).with_for_update().first()

        if not user or not user.email:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Funding user or email not found."
            )

        customer_email = (
            payment.get("customer", {}).get("email", "")
            .strip().lower()
        )

        if customer_email != user.email.strip().lower():
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Payment email does not match."
            )

        # 6. Credit the wallet and mark the transaction atomically.
        user.wallet_balance += transaction.amount
        transaction.status = "success"

        db.commit()

        return {"status": "received"}

    except HTTPException:
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
    reference = secrets.token_urlsafe(24)

    payload = {
    "email": current_user.email,
    "amount": int(request.amount * Decimal("100")),
    "reference": reference,
    "callback_url": "https://handbags-heating-importance-tools.trycloudflare.com/payment-success",
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

        data = response.json()

        if not response.ok or not data.get("status"):
            raise HTTPException(
                status_code=502,
                detail=data.get(
                    "message",
                    "Unable to initialize payment."
                )
            )

    except requests.Timeout:
        raise HTTPException(
            status_code=504,
            detail="Paystack request timed out. Please try again."
        )

    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Unable to connect to Paystack. Please try again."
        )

    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="Paystack returned an invalid response."
        )


    transaction = WalletTransaction(
    user_id=current_user.id,
    transaction_type="funding",
    amount=request.amount,
    status="pending",
    reference=data["data"]["reference"],
    gateway="paystack"
)

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return {
        "authorization_url": data["data"]["authorization_url"],
        "reference": data["data"]["reference"],
        "amount": float(transaction.amount),
        "status": transaction.status
    }


@app.post("/paystack/webhook")
async def paystack_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    # Read the original request body for signature verification.
    raw_body = await request.body()

    signature = request.headers.get("x-paystack-signature")

    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing Paystack signature"
        )

    expected_signature = hmac.new(
        PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid Paystack signature"
        )

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid webhook payload"
        )

    # Process successful charge events only.
    if payload.get("event") != "charge.success":
        return {"status": "ignored"}

    payment_data = payload.get("data", {})

    if payment_data.get("status") != "success":
        return {
            "status": "ignored",
            "message": "Payment has not succeeded"
        }

    reference = payment_data.get("reference")

    if not reference:
        raise HTTPException(
            status_code=400,
            detail="Missing payment reference"
        )

    # Confirm the payment directly with Paystack.
    try:
        verification_response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers={
                "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
            },
            timeout=15
        )
        verification_response.raise_for_status()
        verification_result = verification_response.json()

    except requests.RequestException:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail="Unable to verify payment with Paystack"
        )

    verified_payment = verification_result.get("data", {})

    if (
        not verification_result.get("status")
        or verified_payment.get("status") != "success"
        or verified_payment.get("reference") != reference
        or verified_payment.get("currency") != "NGN"
    ):
        return {
            "status": "ignored",
            "message": "Paystack verification did not confirm payment"
        }

    # Lock the transaction to prevent duplicate wallet credits.
    try:
        transaction = (
            db.query(WalletTransaction)
            .filter(WalletTransaction.reference == reference)
            .with_for_update()
            .first()
        )

        if not transaction:
            return {
                "status": "ignored",
                "reason": "Unknown reference"
            }

        if transaction.transaction_type != "funding":
            return {
                "status": "ignored",
                "reason": "Not a wallet funding transaction"
            }

        if transaction.gateway != "paystack":
            return {
                "status": "ignored",
                "reason": "Transaction does not belong to Paystack"
            }

        if transaction.status == "success":
            return {
                "status": "success",
                "message": "Payment has already been credited"
            }

        if transaction.status != "pending":
            return {
                "status": "ignored",
                "message": "Transaction is not pending"
            }

        # Validate the verified amount and currency.
        if verified_payment.get("currency") != "NGN":
            raise HTTPException(
                status_code=400,
                detail="Payment currency does not match"
            )

        paystack_amount = (
            Decimal(str(verified_payment.get("amount", 0)))
            / Decimal("100")
        )
        transaction_amount = Decimal(str(transaction.amount))

        if paystack_amount != transaction_amount:
            raise HTTPException(
                status_code=400,
                detail="Payment amount does not match the transaction"
            )

        # Credit the wallet and update the transaction atomically.
        result = db.execute(
            update(User)
            .where(User.id == transaction.user_id)
            .values(
                wallet_balance=(
                    User.wallet_balance + transaction.amount
                )
            )
        )

        if result.rowcount != 1:
            raise HTTPException(
                status_code=404,
                detail="Wallet owner not found"
            )

        transaction.status = "success"
        db.commit()

        return {
            "status": "success",
            "message": "Payment verified and wallet credited"
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to process Paystack webhook"
        )



@app.get("/payment-success")
def payment_success(reference: str):
    return FileResponse("payment-success.html")


@app.get("/paystack/verify/{reference}")
def verify_paystack_payment(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
    }

    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=headers,
            timeout=15
        )
        response.raise_for_status()
        data = response.json()

        print("VERIFY PAYSTACK HTTP STATUS:", response.status_code)
        print("VERIFY PAYSTACK STATUS:", data.get("status"))
        print("VERIFY PAYSTACK MESSAGE:", data.get("message"))

    except requests.RequestException as exc:
         print("PAYSTACK VERIFICATION REQUEST ERROR:", repr(exc))
         raise HTTPException(
            status_code=502,
            detail="Unable to contact Paystack. Please check the server logs."
        )

    if not data.get("status"):
        raise HTTPException(
        status_code=502,
        detail="Paystack returned an invalid verification response."
    )
    payment_data = data.get("data", {})

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


    if transaction.transaction_type != "funding":
        raise HTTPException(
            status_code=400,
            detail="Transaction is not a wallet funding transaction."
        )

    if transaction.gateway != "paystack":
        raise HTTPException(
            status_code=400,
            detail="This transaction does not belong to Paystack."
        )


    if transaction.status == "success":
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

    try:
        db.execute(
            update(User)
            .where(User.id == current_user.id)
            .values(
                wallet_balance=User.wallet_balance + transaction.amount
            )
        )

        transaction.status = "success"
        db.commit()

    except Exception:
        db.rollback()
        raise

    db.refresh(current_user)
    db.refresh(transaction)

    return {
        "message": "Payment verified and wallet credited successfully.",
        "status": transaction.status,
        "reference": transaction.reference,
        "amount": float(transaction.amount),
        "wallet_balance": float(current_user.wallet_balance)
    }



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

