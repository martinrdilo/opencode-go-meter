"""Tests for ocgo.api: transport injected or urlopen patched; no network."""

import io
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


def _billing_payload() -> dict:
    """The live billing/status capture (odd/tasks/credits-panel.md, 2026-10-10)."""
    return {
        "billingMode": "prepaid",
        "mode": "pay-as-you-go",
        "balanceMicroCents": "312600514",
        "creditLimitMicroCents": None,
        "availableMicroCents": "312600514",
        "canPurchaseCredits": True,
        "canEnableAutoRecharge": True,
    }


def _auto_recharge_payload() -> dict:
    """The live billing/auto-recharge capture (2026-10-10)."""
    return {
        "enabled": False,
        "thresholdDollars": 5,
        "rechargeAmountDollars": 20,
        "pending": False,
        "failureReason": None,
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
                "extra_usage": None,
                "credits": None,
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

    def test_extra_usage_true_when_use_balance_is_true(self):
        payload = _payload()
        payload["useBalance"] = True
        data = api.to_cache_schema(payload, now=self.NOW)
        self.assertIs(data["extra_usage"], True)

    def test_extra_usage_false_when_use_balance_is_false(self):
        payload = _payload()
        payload["useBalance"] = False
        data = api.to_cache_schema(payload, now=self.NOW)
        self.assertIs(data["extra_usage"], False)

    def test_extra_usage_absent_is_null(self):
        data = api.to_cache_schema(_payload(), now=self.NOW)
        self.assertIsNone(data["extra_usage"])

    def test_extra_usage_non_bool_is_null(self):
        payload = _payload()
        payload["useBalance"] = "yes"
        data = api.to_cache_schema(payload, now=self.NOW)
        self.assertIsNone(data["extra_usage"])

    def test_credits_is_null_until_the_cli_fills_it(self):
        data = api.to_cache_schema(_payload(), now=self.NOW)
        self.assertIsNone(data["credits"])


class BillingFetchTests(unittest.TestCase):
    def test_request_shape(self):
        transport = RecordingTransport(json.dumps(_billing_payload()).encode("utf-8"))
        payload = api.fetch_billing_status("secret-token", transport=transport)
        self.assertEqual(payload, _billing_payload())
        headers = {
            key.lower(): value for key, value in transport.request.headers.items()
        }
        self.assertEqual(transport.request.full_url, api.BILLING_STATUS_URL)
        self.assertEqual(transport.request.get_method(), "GET")
        self.assertEqual(headers["authorization"], "Bearer secret-token")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "ocgo/0.1")
        self.assertEqual(transport.timeout, 20)

    def test_default_transport_is_urlopen(self):
        body = json.dumps(_billing_payload()).encode("utf-8")
        with mock.patch("ocgo.api.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = body
            self.assertEqual(api.fetch_billing_status("tok"), _billing_payload())
        urlopen.assert_called_once()
        self.assertEqual(
            urlopen.call_args.args[0].full_url, api.BILLING_STATUS_URL
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 20)

    def test_http_401_is_billing_rejected(self):
        error = urllib.error.HTTPError(
            api.BILLING_STATUS_URL, 401, "Unauthorized", {}, None
        )
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_billing_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception),
            "billing request rejected (HTTP 401) — credits are available only "
            "for the OpenCode login account",
        )
        self.assertNotIsInstance(caught.exception, api.ApiAuthError)

    def test_http_403_is_billing_rejected(self):
        error = urllib.error.HTTPError(
            api.BILLING_STATUS_URL, 403, "Forbidden", {}, None
        )
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_billing_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception),
            "billing request rejected (HTTP 403) — credits are available only "
            "for the OpenCode login account",
        )
        self.assertNotIsInstance(caught.exception, api.ApiEntitlementError)

    def test_http_500_is_network_error(self):
        error = urllib.error.HTTPError(
            api.BILLING_STATUS_URL, 500, "Server Error", {}, None
        )
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_billing_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: HTTP 500"
        )

    def test_url_error_is_network_error(self):
        error = urllib.error.URLError("dns failure")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_billing_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: dns failure"
        )

    def test_timeout_is_network_error(self):
        error = TimeoutError("timed out")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_billing_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: timed out"
        )

    def test_invalid_json_body_is_network_error(self):
        transport = RecordingTransport(b"<html>not json</html>")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_billing_status("tok", transport=transport)
        self.assertEqual(
            str(caught.exception),
            "network error contacting opencode.ai: invalid JSON response",
        )


class AutoRechargeFetchTests(unittest.TestCase):
    def test_request_shape(self):
        transport = RecordingTransport(
            json.dumps(_auto_recharge_payload()).encode("utf-8")
        )
        payload = api.fetch_auto_recharge("secret-token", transport=transport)
        self.assertEqual(payload, _auto_recharge_payload())
        headers = {
            key.lower(): value for key, value in transport.request.headers.items()
        }
        self.assertEqual(transport.request.full_url, api.BILLING_AUTO_RECHARGE_URL)
        self.assertEqual(transport.request.get_method(), "GET")
        self.assertEqual(headers["authorization"], "Bearer secret-token")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "ocgo/0.1")
        self.assertEqual(transport.timeout, 20)

    def test_default_transport_is_urlopen(self):
        body = json.dumps(_auto_recharge_payload()).encode("utf-8")
        with mock.patch("ocgo.api.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = body
            self.assertEqual(
                api.fetch_auto_recharge("tok"), _auto_recharge_payload()
            )
        urlopen.assert_called_once()
        self.assertEqual(
            urlopen.call_args.args[0].full_url, api.BILLING_AUTO_RECHARGE_URL
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 20)

    def test_http_401_is_billing_rejected(self):
        error = urllib.error.HTTPError(
            api.BILLING_AUTO_RECHARGE_URL, 401, "Unauthorized", {}, None
        )
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_auto_recharge("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception),
            "billing request rejected (HTTP 401) — credits are available only "
            "for the OpenCode login account",
        )
        self.assertNotIsInstance(caught.exception, api.ApiAuthError)

    def test_http_403_is_billing_rejected(self):
        error = urllib.error.HTTPError(
            api.BILLING_AUTO_RECHARGE_URL, 403, "Forbidden", {}, None
        )
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_auto_recharge("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception),
            "billing request rejected (HTTP 403) — credits are available only "
            "for the OpenCode login account",
        )
        self.assertNotIsInstance(caught.exception, api.ApiEntitlementError)

    def test_http_500_is_network_error(self):
        error = urllib.error.HTTPError(
            api.BILLING_AUTO_RECHARGE_URL, 500, "Server Error", {}, None
        )
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_auto_recharge("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: HTTP 500"
        )

    def test_url_error_is_network_error(self):
        error = urllib.error.URLError("dns failure")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_auto_recharge("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: dns failure"
        )

    def test_timeout_is_network_error(self):
        error = TimeoutError("timed out")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_auto_recharge("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: timed out"
        )

    def test_invalid_json_body_is_network_error(self):
        transport = RecordingTransport(b"<html>not json</html>")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_auto_recharge("tok", transport=transport)
        self.assertEqual(
            str(caught.exception),
            "network error contacting opencode.ai: invalid JSON response",
        )


class CreditsFromBillingTests(unittest.TestCase):
    def test_maps_live_capture_to_cache_block(self):
        credits = api.credits_from_billing(_billing_payload(), _auto_recharge_payload())
        self.assertEqual(
            credits,
            {
                "available_usd": 3.126,
                "state": "low",
                "billing_mode": "prepaid",
                "auto_recharge": {
                    "enabled": False,
                    "threshold_usd": 5.0,
                    "amount_usd": 20.0,
                    "pending": False,
                    "failed": False,
                },
            },
        )

    def test_accepts_numeric_available_microcents(self):
        billing = _billing_payload()
        billing["availableMicroCents"] = 312600514
        credits = api.credits_from_billing(billing, None)
        self.assertEqual(credits["available_usd"], 3.126)

    def test_empty_state_at_zero_balance(self):
        billing = _billing_payload()
        billing["availableMicroCents"] = "0"
        credits = api.credits_from_billing(billing, _auto_recharge_payload())
        self.assertEqual(credits["available_usd"], 0.0)
        self.assertEqual(credits["state"], "empty")

    def test_ok_state_above_five_dollars(self):
        billing = _billing_payload()
        billing["availableMicroCents"] = "500000000"
        credits = api.credits_from_billing(billing, _auto_recharge_payload())
        self.assertEqual(credits["state"], "ok")

    def test_non_prepaid_is_always_ok(self):
        billing = _billing_payload()
        billing["billingMode"] = "credit"
        billing["availableMicroCents"] = "0"
        credits = api.credits_from_billing(billing, _auto_recharge_payload())
        self.assertEqual(credits["state"], "ok")
        self.assertEqual(credits["billing_mode"], "credit")

    def test_missing_billing_mode_is_null_and_never_low(self):
        billing = _billing_payload()
        del billing["billingMode"]
        credits = api.credits_from_billing(billing, None)
        self.assertIsNone(credits["billing_mode"])
        self.assertEqual(credits["state"], "ok")

    def test_missing_auto_recharge_is_null(self):
        credits = api.credits_from_billing(_billing_payload(), None)
        self.assertIsNone(credits["auto_recharge"])
        self.assertEqual(credits["state"], "low")  # no recharge -> not healthy

    def test_healthy_auto_recharge_suppresses_low(self):
        auto = dict(_auto_recharge_payload(), enabled=True)
        credits = api.credits_from_billing(_billing_payload(), auto)
        self.assertFalse(credits["auto_recharge"]["failed"])
        self.assertEqual(credits["state"], "ok")

    def test_failed_auto_recharge_does_not_lower_a_healthy_balance(self):
        billing = _billing_payload()
        billing["availableMicroCents"] = "1000000000"  # $10.00
        auto = dict(_auto_recharge_payload(), enabled=True, failureReason="declined")
        credits = api.credits_from_billing(billing, auto)
        self.assertTrue(credits["auto_recharge"]["failed"])
        self.assertEqual(credits["state"], "ok")

    def test_failed_auto_recharge_below_the_threshold_is_low(self):
        auto = dict(_auto_recharge_payload(), enabled=True, failureReason="declined")
        credits = api.credits_from_billing(_billing_payload(), auto)
        self.assertTrue(credits["auto_recharge"]["failed"])
        self.assertEqual(credits["state"], "low")

    def test_tolerant_auto_recharge_fields_default(self):
        credits = api.credits_from_billing(_billing_payload(), {})
        self.assertEqual(
            credits["auto_recharge"],
            {
                "enabled": False,
                "threshold_usd": None,
                "amount_usd": None,
                "pending": False,
                "failed": False,
            },
        )

    def test_bad_dollar_fields_are_null(self):
        auto = dict(
            _auto_recharge_payload(),
            thresholdDollars="nope",
            rechargeAmountDollars=None,
        )
        credits = api.credits_from_billing(_billing_payload(), auto)
        self.assertIsNone(credits["auto_recharge"]["threshold_usd"])
        self.assertIsNone(credits["auto_recharge"]["amount_usd"])

    def test_missing_available_microcents_is_rejected(self):
        billing = _billing_payload()
        del billing["availableMicroCents"]
        with self.assertRaises(api.ApiError) as caught:
            api.credits_from_billing(billing, None)
        self.assertIn("availableMicroCents", str(caught.exception))

    def test_bad_available_microcents_is_rejected(self):
        billing = _billing_payload()
        billing["availableMicroCents"] = "not-a-number"
        with self.assertRaises(api.ApiError):
            api.credits_from_billing(billing, None)

    def test_non_dict_billing_is_rejected(self):
        with self.assertRaises(api.ApiError):
            api.credits_from_billing([1, 2], None)


def _zen_payload() -> dict:
    """The zen usage shape from odd/tasks/multi-account.md (2026-10-02)."""
    return {
        "usage": {
            "rolling": {
                "status": "ok",
                "percent": 12,
                "resetsAt": "2026-10-02T03:46:18.527Z",
            },
            "weekly": {
                "status": "ok",
                "percent": 64,
                "resetsAt": "2026-10-05T00:00:00.000Z",
            },
            "monthly": {
                "status": "ok",
                "percent": 58,
                "resetsAt": "2026-10-11T02:26:15.000Z",
            },
        }
    }


def _http_error(code: int, payload: dict) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))
    return urllib.error.HTTPError(api.ZEN_API_URL, code, "err", {}, body)


class ZenFetchTests(unittest.TestCase):
    def test_request_shape(self):
        transport = RecordingTransport(json.dumps(_zen_payload()).encode("utf-8"))
        payload = api.fetch_zen_status("oc_sk_secret", transport=transport)
        self.assertEqual(payload, _zen_payload())
        headers = {
            key.lower(): value for key, value in transport.request.headers.items()
        }
        self.assertEqual(transport.request.full_url, api.ZEN_API_URL)
        self.assertEqual(transport.request.get_method(), "GET")
        self.assertEqual(headers["authorization"], "Bearer oc_sk_secret")
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(headers["user-agent"], "ocgo/0.1")
        self.assertEqual(transport.timeout, 20)

    def test_default_transport_is_urlopen(self):
        body = json.dumps(_zen_payload()).encode("utf-8")
        with mock.patch("ocgo.api.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = body
            self.assertEqual(api.fetch_zen_status("tok"), _zen_payload())
        self.assertEqual(urlopen.call_args.args[0].full_url, api.ZEN_API_URL)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 20)

    def test_http_401_is_auth_error(self):
        error = urllib.error.HTTPError(api.ZEN_API_URL, 401, "Unauthorized", {}, None)
        with self.assertRaises(api.ApiAuthError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(str(caught.exception), "the API key was rejected (HTTP 401)")
        self.assertIsInstance(caught.exception, api.ApiError)

    def test_http_403_entitlement_error(self):
        error = _http_error(403, {"error": {"type": "EntitlementError"}})
        with self.assertRaises(api.ApiEntitlementError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception),
            "this account has no active OpenCode Go subscription",
        )
        self.assertIsInstance(caught.exception, api.ApiError)

    def test_http_403_without_entitlement_is_api_error(self):
        error = _http_error(403, {"error": {"type": "OtherError"}})
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertNotIsInstance(caught.exception, api.ApiEntitlementError)
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: HTTP 403"
        )

    def test_http_403_bodyless_is_api_error(self):
        error = urllib.error.HTTPError(api.ZEN_API_URL, 403, "Forbidden", {}, None)
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertNotIsInstance(caught.exception, api.ApiEntitlementError)

    def test_http_403_malformed_body_is_api_error(self):
        error = urllib.error.HTTPError(
            api.ZEN_API_URL, 403, "Forbidden", {}, io.BytesIO(b"not json")
        )
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertNotIsInstance(caught.exception, api.ApiEntitlementError)

    def test_http_500_is_network_error(self):
        error = urllib.error.HTTPError(api.ZEN_API_URL, 500, "Server Error", {}, None)
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: HTTP 500"
        )

    def test_url_error_is_network_error(self):
        error = urllib.error.URLError("dns failure")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception),
            "network error contacting opencode.ai: dns failure",
        )

    def test_timeout_is_network_error(self):
        error = TimeoutError("timed out")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_zen_status("tok", transport=RecordingTransport(error=error))
        self.assertEqual(
            str(caught.exception), "network error contacting opencode.ai: timed out"
        )

    def test_invalid_json_body_is_network_error(self):
        transport = RecordingTransport(b"<html>not json</html>")
        with self.assertRaises(api.ApiError) as caught:
            api.fetch_zen_status("tok", transport=transport)
        self.assertEqual(
            str(caught.exception),
            "network error contacting opencode.ai: invalid JSON response",
        )


class ToCacheSchemaZenTests(unittest.TestCase):
    NOW = datetime(2026, 10, 2, 1, 15, 0, tzinfo=timezone.utc)

    def test_maps_zen_capture_to_schema_v1(self):
        data = api.to_cache_schema_zen(_zen_payload(), now=self.NOW)
        self.assertEqual(
            data,
            {
                "schema": 1,
                "fetched_at": "2026-10-02T01:15:00Z",
                "last_error": None,
                "last_error_at": None,
                "product": "go",
                "renewal_ends_at": "2026-10-11T02:26:15Z",
                "windows": {
                    "rolling": {
                        "percent": 12,
                        "used_usd": None,
                        "limit_usd": None,
                        "resets_at": "2026-10-02T03:46:18Z",
                    },
                    "weekly": {
                        "percent": 64,
                        "used_usd": None,
                        "limit_usd": None,
                        "resets_at": "2026-10-05T00:00:00Z",
                    },
                    "monthly": {
                        "percent": 58,
                        "used_usd": None,
                        "limit_usd": None,
                        "resets_at": "2026-10-11T02:26:15Z",
                    },
                },
                "extra_usage": None,
                "credits": None,
            },
        )

    def test_extra_usage_and_credits_are_always_null(self):
        data = api.to_cache_schema_zen(_zen_payload(), now=self.NOW)
        self.assertIsNone(data["extra_usage"])
        self.assertIsNone(data["credits"])

    def test_fractional_percent_is_rounded_to_int(self):
        payload = _zen_payload()
        payload["usage"]["rolling"]["percent"] = 12.6
        data = api.to_cache_schema_zen(payload, now=self.NOW)
        self.assertEqual(data["windows"]["rolling"]["percent"], 13)

    def test_used_and_limit_usd_are_always_null(self):
        data = api.to_cache_schema_zen(_zen_payload(), now=self.NOW)
        for window in data["windows"].values():
            self.assertIsNone(window["used_usd"])
            self.assertIsNone(window["limit_usd"])

    def test_malformed_percent_is_rejected(self):
        for value in ["12", True, None, float("nan"), float("inf"), -float("inf")]:
            with self.subTest(value=repr(value)):
                payload = _zen_payload()
                payload["usage"]["weekly"]["percent"] = value
                with self.assertRaises(api.ApiError):
                    api.to_cache_schema_zen(payload, now=self.NOW)

    def test_missing_usage_is_rejected(self):
        with self.assertRaises(api.ApiError):
            api.to_cache_schema_zen({}, now=self.NOW)

    def test_non_dict_payload_is_rejected(self):
        with self.assertRaises(api.ApiError):
            api.to_cache_schema_zen([1, 2], now=self.NOW)

    def test_missing_meter_is_rejected(self):
        payload = _zen_payload()
        del payload["usage"]["monthly"]
        with self.assertRaises(api.ApiError):
            api.to_cache_schema_zen(payload, now=self.NOW)

    def test_non_dict_meter_is_rejected(self):
        payload = _zen_payload()
        payload["usage"]["weekly"] = [1]
        with self.assertRaises(api.ApiError):
            api.to_cache_schema_zen(payload, now=self.NOW)

    def test_malformed_resets_at_becomes_none(self):
        payload = _zen_payload()
        payload["usage"]["rolling"]["resetsAt"] = "not-a-date"
        payload["usage"]["monthly"]["resetsAt"] = "not-a-date"
        data = api.to_cache_schema_zen(payload, now=self.NOW)
        self.assertIsNone(data["windows"]["rolling"]["resets_at"])
        self.assertIsNone(data["windows"]["monthly"]["resets_at"])
        self.assertIsNone(data["renewal_ends_at"])


if __name__ == "__main__":
    unittest.main()
