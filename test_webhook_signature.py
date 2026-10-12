
import os
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

secret = os.getenv("PAYSTACK_SECRET_KEY")

if not secret:
    raise RuntimeError("PAYSTACK_SECRET_KEY is not configured")
body = b'{"event":"charge.success","data":{"reference":"0APLH__jNUKmeRBd1VPWJl10d8PKemIu","status":"failed","amount":10000,"currency":"NGN"}}'

signature = hmac.new(
    secret.encode("utf-8"),
    body,
    hashlib.sha512
).hexdigest()

response = requests.post(
    "http://127.0.0.1:8000/paystack/webhook",
    data=body,
    headers={
        "Content-Type": "application/json",
        "x-paystack-signature": signature
    },
    timeout=10
)

print("Status:", response.status_code)
print("Response:", response.text)
