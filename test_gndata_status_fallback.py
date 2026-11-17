
import asyncio
import main


class FakeGNClient:
    history_response = []
    history_calls = 0

    async def transaction_status(self, request_id):
        raise main.GNDataError(
            "Simulated individual status HTTP 500",
            status_code=500,
            response_body="Internal Server Error",
        )

    async def transaction_history(self, **kwargs):
        FakeGNClient.history_calls += 1
        assert kwargs["search"] == "GN-REQUEST-123"
        return FakeGNClient.history_response


async def run_tests():
    original_client = main.GNDataClient
    main.GNDataClient = FakeGNClient

    try:
        # Exact matching record: accept verified success.
        FakeGNClient.history_response = [
            {"request_id": "GN-REQUEST-123", "status": "success"}
        ]
        FakeGNClient.history_calls = 0

        result = await main.query_gndata_status("GN-REQUEST-123")
        assert result == "success", result
        assert FakeGNClient.history_calls == 1
        print("PASS: Exact matching history record accepted.")

        # Wrong request ID: remain pending.
        FakeGNClient.history_response = [
            {"request_id": "ANOTHER-REQUEST", "status": "success"}
        ]

        result = await main.query_gndata_status("GN-REQUEST-123")
        assert result == main.PENDING_REQUERY, result
        print("PASS: Unmatched history record remains pending.")

        # Multiple matching records: remain pending.
        FakeGNClient.history_response = [
            {"request_id": "GN-REQUEST-123", "status": "success"},
            {"request_id": "GN-REQUEST-123", "status": "failed"},
        ]

        result = await main.query_gndata_status("GN-REQUEST-123")
        assert result == main.PENDING_REQUERY, result
        print("PASS: Ambiguous history records remain pending.")

        print("\nALL GN STATUS FALLBACK TESTS PASSED.")

    finally:
        main.GNDataClient = original_client


asyncio.run(run_tests())
