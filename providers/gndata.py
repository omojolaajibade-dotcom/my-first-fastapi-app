import os

import logging

logger = logging.getLogger(__name__)

import httpx


class GNDataError(Exception):
    """Raised when a GN Data API request fails."""

    def __init__(self, message, status_code=None, response_body=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or ""

    @property
    def is_definitive_rejection(self):
        if self.status_code != 404:
            return False

        body = self.response_body.lower()

        markers = (
            "route not found",
            "endpoint not found",
            "cannot post",
            "cannot find the requested resource",
        )

        return any(marker in body for marker in markers)

class GNDataClient:
    """Read-only GN Data API client."""

    def __init__(self):
        self.base_url = os.getenv(
            "GNDATA_BASE_URL",
            "https://api.gndata.com.ng/api/v1"
        ).rstrip("/")

        self.api_key = os.getenv("GNDATA_API_KEY")
        self.enabled = (
            os.getenv("GNDATA_ENABLED", "false").lower()
            == "true"
        )

        self.timeout = httpx.Timeout(20.0)

    def _headers(self):
        if not self.enabled:
            raise GNDataError("GN Data is currently disabled.")

        if not self.api_key:
            raise GNDataError("GN Data API key is not configured.")

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    async def _get(self, endpoint):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        logger.info("GN Data request URL: %s", url)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.get(
                    url,
                    headers=self._headers()
                )

                response.raise_for_status()

                result = response.json()

                if not isinstance(result, (dict, list)):
                    raise GNDataError(
                        "GN Data returned an unexpected response."
                    )

                return result
            
        except GNDataError:
            raise

        except httpx.HTTPStatusError as exc:
            response_body = exc.response.text[:2000]

            logger.error(
                "GN DATA ACTUAL GET RESPONSE | "
                "URL=%s | HTTP=%s | Body=%s",
                url,
                exc.response.status_code,
                response_body or "<EMPTY RESPONSE BODY>",
            )

            raise GNDataError(
                f"GN Data returned HTTP {exc.response.status_code}.",
                status_code=exc.response.status_code,
                response_body=response_body,
            ) from exc

        except httpx.TimeoutException as exc:

                   raise GNDataError(
                "GN Data request timed out."
            ) from exc



        except httpx.RequestError as exc:
            raise GNDataError(
                "Unable to connect to GN Data."
            ) from exc

        except ValueError as exc:
            raise GNDataError(
                "GN Data returned invalid JSON."
            ) from exc

    async def wallet_balance(self):
        return await self._get("wallet/balance")

    async def airtime_services(self):
        return await self._get("airtime/services")

    async def data_services(self, include_plans=True):
        endpoint = "data/services"

        if include_plans:
            endpoint += "?include_plans=true"

        return await self._get(endpoint)

    async def data_plans(self, network_id):
        if not isinstance(network_id, int) or network_id <= 0:
            raise GNDataError("Invalid GN Data network ID.")

        return await self._get(
            f"data/plans/{network_id}"
        )

    async def transaction_status(self, request_id):
        from urllib.parse import quote

        if not isinstance(request_id, str) or not request_id.strip():
            raise GNDataError("Invalid GN Data request ID.")

        safe_id = quote(request_id.strip(), safe="")

        return await self._get(
            f"transactions/{safe_id}"
        )

    async def pending_transactions(self):
        return await self._get(
            "transactions?status=pending"
        )

    async def transaction_history(
        self,
        status=None,
        category=None,
        search=None,
        skip=0,
        limit=50
    ):
        from urllib.parse import urlencode

        allowed_statuses = {
            "pending", "success", "failed", "refund"
        }

        allowed_categories = {
            "data_purchase",
            "airtime_purchase",
            "tv_purchase",
            "electricity_purchase",
            "funding"
        }

        if status is not None and status not in allowed_statuses:
            raise GNDataError("Invalid transaction status.")

        if category is not None and category not in allowed_categories:
            raise GNDataError("Invalid transaction category.")

        if not isinstance(skip, int) or skip < 0:
            raise GNDataError("Invalid transaction offset.")

        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise GNDataError("Transaction limit must be between 1 and 100.")

        params = {
            "skip": skip,
            "limit": limit
        }

        if status:
            params["status"] = status

        if category:
            params["category"] = category

        if search:
            params["search"] = search.strip()

        endpoint = "transactions?" + urlencode(params)

        return await self._get(endpoint)


    async def _post(self, endpoint, payload, idempotency_key):
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise GNDataError("A unique idempotency key is required.")

        headers = self._headers()
        headers.update({
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key.strip(),
        })

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout
            ) as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

                result = response.json()

                if not isinstance(result, dict):
                    raise GNDataError(
                        "GN Data returned an unexpected purchase response."
                    )

                return result

        except GNDataError:
            raise

        except httpx.TimeoutException as exc:
            raise GNDataError(
                "GN Data purchase timed out. Check transaction status before retrying."
            ) from exc

        except httpx.HTTPStatusError as exc:
           response_body = exc.response.text[:2000]

           raise GNDataError(
        f"GN Data returned HTTP {exc.response.status_code}.",
        status_code=exc.response.status_code,
        response_body=response_body,
    ) from exc
        except httpx.RequestError as exc:
            raise GNDataError(
                "Unable to connect to GN Data."
            ) from exc

        except ValueError as exc:
            raise GNDataError(
                "GN Data returned invalid JSON."
            ) from exc

    async def purchase_airtime(
        self,
        phone,
        amount,
        network_id,
        idempotency_key,
    ):
        if not isinstance(network_id, int) or network_id <= 0:
            raise GNDataError("Invalid GN Data airtime network ID.")

        if not isinstance(amount, int) or amount <= 0:
            raise GNDataError("Airtime amount must be a positive integer.")

        if not isinstance(phone, str) or not phone.strip():
            raise GNDataError("Invalid recipient phone number.")

        return await self._post(
            "airtime/purchase",
            {
                "phone": phone.strip(),
                "amount": amount,
                "id": network_id,
            },
            idempotency_key,
        )

    async def purchase_data(
        self,
        phone,
        network_id,
        plan_id,
        idempotency_key,
    ):
        if not isinstance(network_id, int) or network_id <= 0:
            raise GNDataError("Invalid GN Data data network ID.")

        if not isinstance(plan_id, int) or plan_id <= 0:
            raise GNDataError("Invalid GN Data data plan ID.")

        if not isinstance(phone, str) or not phone.strip():
            raise GNDataError("Invalid recipient phone number.")

        return await self._post(
            "data/purchase",
            {
                "phone": phone.strip(),
                "network_id": network_id,
                "plan_id": plan_id,
            },
            idempotency_key,
        )
