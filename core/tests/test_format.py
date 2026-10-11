"""Tests for ocgo.format (pure helpers)."""

import unittest
from datetime import datetime, timedelta, timezone

from ocgo import format as fmt

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


class PercentTests(unittest.TestCase):
    def test_rounds_to_nearest_integer(self):
        self.assertEqual(fmt.percent(636, 1000), 64)
        self.assertEqual(fmt.percent(578, 1000), 58)

    def test_matches_console_capture_values(self):
        # Live capture 2026-10-01: fiveHour 2%, week 64%, month 58%.
        self.assertEqual(fmt.percent(18211143, 1200000000), 2)
        self.assertEqual(fmt.percent(1909286550, 3000000000), 64)
        self.assertEqual(fmt.percent(3471303267, 6000000000), 58)

    def test_clamps_to_0_100(self):
        self.assertEqual(fmt.percent(2000, 1000), 100)
        self.assertEqual(fmt.percent(-10, 1000), 0)

    def test_zero_limit_is_zero(self):
        self.assertEqual(fmt.percent(10, 0), 0)


class UsdTests(unittest.TestCase):
    def test_micro_cents_to_usd_with_four_decimals(self):
        self.assertEqual(fmt.usd_from_microcents(18211143), 0.1821)
        self.assertEqual(fmt.usd_from_microcents(1909286550), 19.0929)
        self.assertEqual(fmt.usd_from_microcents(3471303267), 34.713)
        self.assertEqual(fmt.usd_from_microcents(1200000000), 12.0)
        self.assertEqual(fmt.usd_from_microcents(6000000000), 60.0)


class CreditsStateTests(unittest.TestCase):
    def test_non_prepaid_is_always_ok(self):
        for available in (0, -1, 100, 499_999_999, 500_000_000, 1_000_000_000):
            for healthy in (True, False):
                with self.subTest(available=available, healthy=healthy):
                    self.assertEqual(
                        fmt.credits_state(
                            available,
                            prepaid=False,
                            auto_recharge_healthy=healthy,
                        ),
                        "ok",
                    )

    def test_empty_at_or_below_zero(self):
        for available in (0, -1):
            for healthy in (True, False):
                with self.subTest(available=available, healthy=healthy):
                    self.assertEqual(
                        fmt.credits_state(
                            available,
                            prepaid=True,
                            auto_recharge_healthy=healthy,
                        ),
                        "empty",
                    )

    def test_low_below_the_threshold_when_auto_recharge_is_unhealthy(self):
        self.assertEqual(
            fmt.credits_state(312_600_514, prepaid=True, auto_recharge_healthy=False),
            "low",
        )
        self.assertEqual(
            fmt.credits_state(499_999_999, prepaid=True, auto_recharge_healthy=False),
            "low",
        )

    def test_healthy_auto_recharge_suppresses_low(self):
        self.assertEqual(
            fmt.credits_state(312_600_514, prepaid=True, auto_recharge_healthy=True),
            "ok",
        )

    def test_ok_at_and_above_the_threshold(self):
        for available in (500_000_000, 500_000_001, 1_000_000_000):
            for healthy in (True, False):
                with self.subTest(available=available, healthy=healthy):
                    self.assertEqual(
                        fmt.credits_state(
                            available,
                            prepaid=True,
                            auto_recharge_healthy=healthy,
                        ),
                        "ok",
                    )

    def test_low_threshold_constant_is_five_dollars(self):
        self.assertEqual(fmt.CREDITS_LOW_MICROCENTS, 500_000_000)
        self.assertEqual(fmt.usd_from_microcents(fmt.CREDITS_LOW_MICROCENTS), 5.0)


class CountdownTests(unittest.TestCase):
    def test_days_and_hours(self):
        self.assertEqual(fmt.countdown(NOW, NOW + timedelta(days=9, hours=3)), "9d 3h")

    def test_exact_days_keeps_zero_hours(self):
        self.assertEqual(fmt.countdown(NOW, NOW + timedelta(days=3)), "3d 0h")

    def test_hours_and_minutes(self):
        self.assertEqual(fmt.countdown(NOW, NOW + timedelta(hours=4, minutes=24)), "4h 24m")

    def test_minutes_only(self):
        self.assertEqual(fmt.countdown(NOW, NOW + timedelta(minutes=45)), "45m")

    def test_sub_minute_is_zero_minutes(self):
        self.assertEqual(fmt.countdown(NOW, NOW + timedelta(seconds=59)), "0m")

    def test_past_target_is_zero_minutes(self):
        self.assertEqual(fmt.countdown(NOW, NOW - timedelta(hours=1)), "0m")

    def test_values_are_floored(self):
        self.assertEqual(
            fmt.countdown(NOW, NOW + timedelta(days=1, hours=2, minutes=59, seconds=59)),
            "1d 2h",
        )


class ColorTests(unittest.TestCase):
    def test_thresholds(self):
        for value in (0, 49):
            self.assertEqual(fmt.color_for(value), fmt.GREEN)
        for value in (50, 84):
            self.assertEqual(fmt.color_for(value), fmt.AMBER)
        for value in (85, 100):
            self.assertEqual(fmt.color_for(value), fmt.RED)


class IsoTests(unittest.TestCase):
    def test_parse_api_timestamp_with_milliseconds(self):
        parsed = fmt.parse_iso("2026-10-02T03:46:18.527Z")
        self.assertEqual(
            parsed, datetime(2026, 10, 2, 3, 46, 18, 527000, tzinfo=timezone.utc)
        )

    def test_parse_offset_is_normalized_to_utc(self):
        parsed = fmt.parse_iso("2026-10-02T05:46:18+02:00")
        self.assertEqual(parsed, datetime(2026, 10, 2, 3, 46, 18, tzinfo=timezone.utc))

    def test_parse_rejects_none_and_garbage(self):
        self.assertIsNone(fmt.parse_iso(None))
        self.assertIsNone(fmt.parse_iso("not-a-date"))

    def test_iso_utc_drops_microseconds_and_suffixes_z(self):
        value = datetime(2026, 10, 2, 3, 46, 18, 527000, tzinfo=timezone.utc)
        self.assertEqual(fmt.iso_utc(value), "2026-10-02T03:46:18Z")

    def test_naive_datetimes_are_treated_as_utc(self):
        self.assertEqual(
            fmt.iso_utc(datetime(2026, 10, 1, 23, 30, 0)), "2026-10-01T23:30:00Z"
        )


if __name__ == "__main__":
    unittest.main()
