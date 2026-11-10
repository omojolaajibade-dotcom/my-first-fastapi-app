import os

import hashlib

import hmac

from cryptography.fernet import Fernet, InvalidToken

def get_fernet():
    key = os.getenv("ENCRYPTION_KEY")

    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not configured.")

    return Fernet(key.encode())


def encrypt_phone_number(phone_number):
    if not phone_number:
        return phone_number

    return get_fernet().encrypt(
        phone_number.encode("utf-8")
    ).decode("utf-8")


def decrypt_phone_number(encrypted_number):
    if not encrypted_number:
        return encrypted_number

    # Preserve existing plaintext numbers during migration.
    if not encrypted_number.startswith("gAAAA"):
        return encrypted_number

    try:
        return get_fernet().decrypt(
            encrypted_number.encode("utf-8")
        ).decode("utf-8")
    except InvalidToken:
        raise ValueError("Phone number decryption failed.")

    import hashlib


def hash_phone_number(phone_number):
    if not phone_number:
        return None

    secret = os.getenv("PHONE_HASH_KEY")

    if not secret:
        raise RuntimeError("PHONE_HASH_KEY is not configured.")

    normalized = phone_number.strip()

    return hmac.new(
        secret.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()