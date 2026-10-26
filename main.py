import os

import secrets

import hashlib

import hmac

import json

import requests

import pytz

from decimal import Decimal

from datetime import datetime, timedelta, timezone

import jwt

from dotenv import load_dotenv

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


# =========================
# VTPASS SANDBOX CONFIGURATION
# =========================

VTPASS_BASE_URL = "https://sandbox.vtpass.com/api"
VTPASS_API_KEY = os.getenv("VTPASS_API_KEY")
VTPASS_PUBLIC_KEY = os.getenv("VTPASS_PUBLIC_KEY")
VTPASS_SECRET_KEY = os.getenv("VTPASS_SECRET_KEY")


def get_vtpass_headers():
    if not VTPASS_API_KEY or not VTPASS_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="VTpass sandbox credentials are not configured."
        )

    return {
        "api-key": VTPASS_API_KEY,
        "secret-key": VTPASS_SECRET_KEY,
        "Content-Type": "application/json"
    }


# =========================
# DATABASE, JWT AND PAYSTACK CONFIGURATION
# =========================

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
    status = Column(String(20), nullable=False, default="pending")
    reference = Column(String(100), unique=True, nullable=False)
    gateway = Column(String(30), nullable=True)

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp()
    )

# Create tables during normal startup, but let Alembic
# manage schema changes when running migrations.
if os.getenv("OMOTECH_SKIP_CREATE_ALL") != "1":
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
        "https://omotech-airtime-data.onrender.com/payment-success?flow=admin"
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
            "user_phone": user.phone if user else None,
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

# =========================
# APPROVED DATA PLAN CATALOGUE
# =========================

APPROVED_DATA_PLANS = {
    "mtn": {
        "mtn-50mb-200": {
            "name": "MTN 200MB — 2 days",
            "selling_price": 230,
        },
        "mtn-2-5gb-600": {
            "name": "MTN 2.5GB — 2 days",
            "selling_price": 680,
        },
        "mtn-3gb-1500": {
            "name": "MTN 3GB — 30 days",
            "selling_price": 1600,
        },
        "mtn-3gb-2500": {
            "name": "MTN 6GB — 30 days",
            "selling_price": 2750,
        },
        "mtn-data-3000": {
            "name": "MTN 8GB — 30 days",
            "selling_price": 3310,
        },
        "mtn-1gb-3500": {
            "name": "MTN 10GB — 30 days",
            "selling_price": 3740,
        },
        "mtn-100hr-5000": {
            "name": "MTN 15GB — 30 days",
            "selling_price": 5250,
        },
        "mtn-3gb-6000": {
            "name": "MTN 20GB — 30 days",
            "selling_price": 6300,
        },
        "mtn-40gb-10000": {
            "name": "MTN 40GB — 30 days",
            "selling_price": 10500,
        },
    }
}

# =========================
# VTPASS DATA PLANS
# =========================

@app.get("/data/plans/{network}")
def get_data_plans(network: str):
    network_services = {
        "mtn": "mtn-data",
        "airtel": "airtel-data",
        "glo": "glo-data",
        "9mobile": "etisalat-data",
    }

    network_key = network.strip().lower()
    service_id = network_services.get(network_key)

    if not service_id:
        raise HTTPException(
            status_code=400,
            detail="Unsupported network. Use mtn, airtel, glo, or 9mobile."
        )

    if not VTPASS_API_KEY or not VTPASS_PUBLIC_KEY:
        raise HTTPException(
            status_code=503,
            detail="VTpass read-only credentials are not configured."
        )

    headers = {
        "api-key": VTPASS_API_KEY,
        "public-key": VTPASS_PUBLIC_KEY,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{VTPASS_BASE_URL}/service-variations",
            params={"serviceID": service_id},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

    except (requests.RequestException, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve data plans from VTpass."
        )

    if str(result.get("response_description", "")) != "000":
        raise HTTPException(
            status_code=502,
            detail="VTpass did not return a successful data-plan response."
        )

    content = result.get("content") or {}
    variations = content.get("variations") or []

    approved_plans = APPROVED_DATA_PLANS.get(network_key, {})

    plans = []

    for plan in variations:
        variation_code = str(
            plan.get("variation_code") or ""
        ).strip()

        approved = approved_plans.get(variation_code)

        if not approved:
            continue

        plans.append({
            "variation_code": variation_code,
            "name": approved["name"],
            "amount": approved["selling_price"],
        })

    return {
        "network": network_key,
        "service_name": content.get("ServiceName"),
        "plans": plans,
    }

# =========================
# VTPASS DATA PURCHASE
# DISABLED UNTIL AUTHENTICATION IS RESOLVED
# =========================

@app.post("/data/purchase")
def purchase_data(
    request: DataPurchaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=503,
        detail=(
            "Data purchases are temporarily disabled while "
            "VTpass authentication is being resolved."
        ),
    )


def generate_vtpass_request_id() -> str:
    nigeria_timezone = pytz.timezone("Africa/Lagos")
    timestamp = datetime.now(nigeria_timezone).strftime("%Y%m%d%H%M")
    return timestamp + secrets.token_hex(4)


@app.post("/airtime/purchase")
def purchase_airtime(
    request: AirtimePurchaseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not VTPASS_API_KEY or not VTPASS_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="VTpass sandbox credentials are not configured."
        )

    amount = Decimal(str(request.amount))

    if amount != amount.quantize(Decimal("0.01")):
        raise HTTPException(
            status_code=400,
            detail="Amount must have no more than two decimal places."
        )

    # Generate the VTpass request ID using Nigeria's local time.
    reference = generate_vtpass_request_id()

    # Reserve funds and create the pending transaction atomically.
    try:
        user = (
            db.query(User)
            .filter(User.id == current_user.id)
            .with_for_update()
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=404,
                detail="Customer account not found."
            )

        if user.wallet_balance < amount:
            raise HTTPException(
                status_code=400,
                detail="Insufficient wallet balance."
            )

        transaction = WalletTransaction(
            user_id=user.id,
            transaction_type="airtime",
            amount=amount,
            status="pending",
            reference=reference,
            gateway="vtpass"
        )

        user.wallet_balance -= amount
        db.add(transaction)
        db.commit()
        db.refresh(transaction)

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to reserve wallet funds."
        )

    # Send the airtime purchase to VTpass sandbox.
    
    payload = {
    "request_id": reference,
    "serviceID": {
        "MTN": "mtn",
        "Airtel": "airtel",
        "Glo": "glo",
        "9mobile": "etisalat"
    }[request.network],
    "amount": float(amount),
    "phone": request.phone
}


    try:
        response = requests.post(
            f"{VTPASS_BASE_URL}/pay",
            json=payload,
            headers=get_vtpass_headers(),
            timeout=30
        )
        result = response.json()

    except (requests.RequestException, ValueError):
        # The request may have reached VTpass.
        # Keep funds reserved until the outcome is checked.
        return {
            "message": (
                "Purchase outcome is uncertain. "
                "Do not retry this purchase yet."
            ),
            "status": "pending",
            "reference": reference,
            "amount": float(amount)
        }

    response_code = str(result.get("code", ""))
    content = result.get("content") or {}
    details = content.get("transactions") or {}
    vtpass_status = str(details.get("status", "")).lower()

    # Only accept an explicit delivery confirmation.
    if response_code == "000" and vtpass_status == "delivered":
        try:
            transaction.status = "success"
            db.commit()
            db.refresh(user)

            return {
                "message": "Airtime purchase successful.",
                "status": "success",
                "reference": reference,
                "network": request.network,
                "phone": request.phone,
                "amount": float(amount),
                "wallet_balance": float(user.wallet_balance)
            }

        except Exception:
            db.rollback()
            # Do not refund automatically: VTpass may have delivered.
            return {
                "message": (
                    "VTpass reported delivery, but the local "
                    "record needs reconciliation."
                ),
                "status": "pending",
                "reference": reference,
                "amount": float(amount)
            }

    # Refund only when VTpass explicitly reports failure.
    if vtpass_status in ("failed", "failure"):
        try:
            user = (
                db.query(User)
                .filter(User.id == current_user.id)
                .with_for_update()
                .first()
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

            if not user or not transaction:
                db.rollback()
                return {
                    "message": "Purchase requires reconciliation.",
                    "status": "pending",
                    "reference": reference
                }

            if transaction.status == "pending":
                user.wallet_balance += transaction.amount
                transaction.status = "failed"
                db.commit()

            return {
                "message": "Airtime purchase failed; funds refunded.",
                "status": "failed",
                "reference": reference,
                "wallet_balance": float(user.wallet_balance)
            }

        except Exception:
            db.rollback()
            return {
                "message": "Refund requires reconciliation.",
                "status": "pending",
                "reference": reference
            }

    # Processing, unfamiliar responses, and other uncertain outcomes
    # must not be marked successful or automatically refunded.
    return {
        "message": (
            "VTpass has not confirmed delivery or failure. "
            "Do not retry this purchase yet."
        ),
        "status": "pending",
        "reference": reference,
        "amount": float(amount),
        "vtpass_response": result
    }


@app.post("/airtime/verify/{reference}")
def verify_airtime_purchase(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    transaction = (
        db.query(WalletTransaction)
        .filter(
            WalletTransaction.reference == reference,
            WalletTransaction.user_id == current_user.id,
            WalletTransaction.transaction_type == "airtime",
            WalletTransaction.gateway == "vtpass"
        )
        .with_for_update()
        .first()
    )

    if not transaction:
        raise HTTPException(
            status_code=404,
            detail="Airtime transaction not found."
        )

    if transaction.status in ("success", "failed"):
        return {
            "reference": reference,
            "status": transaction.status,
            "amount": float(transaction.amount)
        }

    try:
        response = requests.post(
            f"{VTPASS_BASE_URL}/requery",
            json={"request_id": reference},
            headers=get_vtpass_headers(),
            timeout=30
        )
        response.raise_for_status()
        result = response.json()

    except (requests.RequestException, ValueError):
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to confirm the VTpass transaction. "
                "Your transaction remains pending; do not retry the purchase."
            )
        )

    code = str(result.get("code", ""))
    content = result.get("content") or {}
    details = content.get("transactions") or {}
    status = str(details.get("status", "")).lower()

    # Confirmed delivery
    if code == "000" and status == "delivered":
        transaction.status = "success"
        db.commit()

        return {
            "reference": reference,
            "status": "success",
            "amount": float(transaction.amount)
        }

    # Refund only for documented terminal outcomes.
    definitive_failure = (
        code in ("016", "091")
        or (code == "040" and status == "reversed")
    )

    if definitive_failure:
        user = (
            db.query(User)
            .filter(User.id == current_user.id)
            .with_for_update()
            .first()
        )

        if not user:
            db.rollback()
            raise HTTPException(
                status_code=404,
                detail="Customer account not found."
            )

        # The transaction row is locked; refund only once.
        if transaction.status == "pending":
            user.wallet_balance += transaction.amount
            transaction.status = "failed"
            db.commit()

            return {
                "reference": reference,
                "status": "failed",
                "message": "Purchase failed; funds refunded.",
                "wallet_balance": float(user.wallet_balance)
            }

        db.rollback()

        return {
            "reference": reference,
            "status": transaction.status,
            "message": "Transaction status was already updated."
        }

    # Unclear or non-final response: never refund automatically.
    db.rollback()

    return {
        "reference": reference,
        "status": "pending",
        "message": (
            "VTpass has not confirmed a final result. "
            "Do not submit another purchase."
        ),
        "vtpass_code": code,
        "vtpass_description": result.get("response_description"),
        "vtpass_status": status or None
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
    "https://omotech-airtime-data.onrender.com/payment-success"
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

