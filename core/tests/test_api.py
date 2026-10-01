"""Tests for ocgo.api: transport injected or urlopen patched; no network."""

import json
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest import mock

from ocgo import api


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class RecordingTransport:
    def __init__(self, body: bytes | None = None, error: Exception | None = None):
        self.body = body
        self.error = error
        self.request = None
        self.timeout = None
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        self.request = request
        self.timeout = timeout
        if self.error is not None:
            raise self.error
        return FakeResponse(self.body or b"")


def _payload() -> dict:
    """The live capture from odd/tasks/opencode-go-meter.md (2026-10-01)."""
    return {
        "product": "go",
        "access": {
            "endsAt": "2026-10-11T02:26:15.000Z",
            "meters": {
                "fiveHour": {
                    "resetsAt": "2026-10-02T03:46:18.527Z",
                    "limitMicroCents": "1200000000",
                    "usedMicroCents": "18211143",
                },
                "week": {
                    "resetsAt": "2026-10-05T00:00:00.000Z",
                    "limitMicroCents": "3000000000",
                    "usedMicroCents": "1909286550",
                },
                "month": {
                    "limitMicroCents": "6000000000",
                    "usedMicroCents": "3471303267",
                },
            },
        },
    }


class FetchStatusTests(unittest.TestCase):
    def test_request_shape(self):
        transport = RecordingTransport(json.dumps(_payload()).encode("utf-8"))
        payload = api.fetch_status("secret-token", transport=transport)
        self.assertEqual(payload, _payload())
        headers = {
            key.lower(): value for key, value in transport.request.headers.items()
        }
        self.assertEqual(transport.request.full_url, api.API_URL)
        self.assertEqual(transport.request.get_method(), "GET")
        self.assertEqual(headers["authorization"], "Bearer secret-token")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "ocgo/0.1")
        self.assertEqual(transport.timeout, 20)

    def test_default_transport_is_urlopen(self):
        body = json.dumps(_payload()).encode("utf-8")
        with mock.patch("ocgo.api.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = body
            self.assertEqual(api.fetch_status("tok"), _payload())
        urlopen.assert_called_once()
        self.assertEqual(urlopen.call_args.args[0].full_url, api.API_URL)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 20)

    def test_http_401_is_credential_rejected(self):
        error = urllib.error.HTTPError(api.API_URL, 401, "Unauthorized", {}, None)
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception),
            "credential rejected (HTTP 401) — open OpenCode to refresh it, "
            "or check your account.",
        )

    def test_http_403_is_credential_rejected(self):
        error = urllib.error.HTTPError(api.API_URL, 403, "Forbidden", {}, None)
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_status("tok", transport=RecordingTransport(error=error))
        self.assertIn("credential rejected (HTTP 403)", str(caught.exception))

    def test_http_500_is_network_error(self):
        error = urllib.error.HTTPError(api.API_URL, 500, "Server Error", {}, None)
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: HTTP 500"
        )

    def test_url_error_is_network_error(self):
        error = urllib.error.URLError("dns failure")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: dns failure"
        )

    def test_timeout_is_network_error(self):
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_status("tok", transport=RecordingTransport(error=TimeoutError("timed out")))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: timed out"
        )

    def test_invalid_json_body_is_network_error(self):
        transport = RecordingTransport(b"<html>not json</html>")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_status("tok", transport=transport)
        self.assertEqual(
            str(caught.exception),
            "network error contacting opencode.ai: invalid JSON response",
        )


class ToCacheSchemaTests(unittest.TestCase):
    NOW = datetime(2026, 10, 1, 23, 30, 0, tzinfo=timezone.utc)

    def test_maps_live_capture_to_schema_v1(self):
        data = api.to_cache_schema(_payload(), now=self.NOW)
        self.assertEqual(
            data,
            {
                "schema": 1,
                "fetched_at": "2026-10-01T23:30:00Z",
                "last_error": None,
                "last_error_at": None,
                "product": "go",
                "renewal_ends_at": "2026-10-11T02:26:15Z",
                "windows": {
                    "rolling": {
                        "percent": 2,
                        "used_usd": 0.1821,
                        "limit_usd": 12.0,
                        "resets_at": "2026-10-02T03:46:18Z",
                    },
                    "weekly": {
                        "percent": 64,
                        "used_usd": 19.0929,
                        "limit_usd": 30.0,
                        "resets_at": "2026-10-05T00:00:00Z",
                    },
                    "monthly": {
                        "percent": 58,
                        "used_usd": 34.713,
                        "limit_usd": 60.0,
                        "resets_at": None,
                    },
                },
            },
        )

    def test_accepts_numeric_microcents(self):
        payload = _payload()
        payload["access"]["meters"]["fiveHour"]["usedMicroCents"] = 18211143
        data = api.to_cache_schema(payload, now=self.NOW)
        self.assertEqual(data["windows"]["rolling"]["percent"], 2)

    def test_monthly_resets_at_is_always_null(self):
        payload = _payload()
        payload["access"]["meters"]["month"]["resetsAt"] = "2026-10-08T00:00:00.000Z"
        data = api.to_cache_schema(payload, now=self.NOW)
        self.assertIsNone(data["windows"]["monthly"]["resets_at"])

    def test_missing_meters_is_rejected(self):
        with self.assertRaises(api.ApiError):
            api.to_cache_schema({"product": "go", "access": {}}, now=self.NOW)

    def test_missing_meter_is_rejected(self):
        payload = _payload()
        del payload["access"]["meters"]["week"]
        with self.assertRaises(api.ApiError):
            api.to_cache_schema(payload, now=self.NOW)

    def test_bad_microcents_are_rejected(self):
        payload = _payload()
        payload["access"]["meters"]["month"]["usedMicroCents"] = "not-a-number"
        with self.assertRaises(api.ApiError):
            api.to_cache_schema(payload, now=self.NOW)


if __name__ == "__main__":
    unittest.main()
