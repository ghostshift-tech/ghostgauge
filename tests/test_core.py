"""Tests for pure/data logic in core.py. No rumps, no AppKit — runs on Linux CI."""

import sys
import types

# ---------------------------------------------------------------------------
# Stub keyring before importing core so the import never fails on CI
# ---------------------------------------------------------------------------
if "keyring" not in sys.modules:
    _stub = types.ModuleType("keyring")
    _stub.get_password = lambda service, username: None  # type: ignore[attr-defined]
    sys.modules["keyring"] = _stub

import core  # noqa: E402, I001


# ---------------------------------------------------------------------------
# bar()
# ---------------------------------------------------------------------------

class TestBar:
    def test_empty_bar(self):
        result = core.bar(0, width=10)
        assert result == "░" * 10

    def test_full_bar(self):
        result = core.bar(100, width=10)
        assert result == "█" * 10

    def test_half_bar(self):
        result = core.bar(50, width=10)
        assert result == "█" * 5 + "░" * 5

    def test_clamps_below_zero(self):
        result = core.bar(-10, width=10)
        assert result == "░" * 10

    def test_clamps_above_100(self):
        result = core.bar(150, width=10)
        assert result == "█" * 10

    def test_custom_width(self):
        result = core.bar(50, width=14)
        assert len(result) == 14

    def test_rounding(self):
        # 33% of 10 = 3.3 → rounds to 3
        result = core.bar(33, width=10)
        assert result.count("█") == 3
        assert result.count("░") == 7


# ---------------------------------------------------------------------------
# extract_pct()
# ---------------------------------------------------------------------------

class TestExtractPct:
    def test_reads_utilization(self):
        assert core.extract_pct({"utilization": 40}) == 40

    def test_reads_used_percentage(self):
        assert core.extract_pct({"used_percentage": 55}) == 55

    def test_reads_used(self):
        assert core.extract_pct({"used": 70}) == 70

    def test_reads_percentage(self):
        assert core.extract_pct({"percentage": 90}) == 90

    def test_value_1_returns_1_not_100(self):
        # Value is already 0-100 — no fraction guessing
        assert core.extract_pct({"utilization": 1}) == 1

    def test_missing_key_returns_none(self):
        assert core.extract_pct({}) is None

    def test_non_numeric_returns_none(self):
        assert core.extract_pct({"utilization": "not-a-number"}) is None

    def test_none_value_returns_none(self):
        assert core.extract_pct({"utilization": None}) is None

    def test_priority_order(self):
        # utilization takes priority over used_percentage
        result = core.extract_pct({"utilization": 10, "used_percentage": 99})
        assert result == 10


# ---------------------------------------------------------------------------
# extract_reset()
# ---------------------------------------------------------------------------

class TestExtractReset:
    def test_reads_resets_at(self):
        assert core.extract_reset({"resets_at": "2026-06-10T12:00:00Z"}) == "2026-06-10T12:00:00Z"

    def test_reads_reset_at(self):
        assert core.extract_reset({"reset_at": "2026-06-10T12:00:00Z"}) == "2026-06-10T12:00:00Z"

    def test_reads_resetsAt(self):
        assert core.extract_reset({"resetsAt": "2026-06-10T12:00:00Z"}) == "2026-06-10T12:00:00Z"

    def test_missing_returns_none(self):
        assert core.extract_reset({}) is None

    def test_unrelated_key_returns_none(self):
        assert core.extract_reset({"expires_at": "2026-06-10T12:00:00Z"}) is None


# ---------------------------------------------------------------------------
# format_reset_relative()
# ---------------------------------------------------------------------------

class TestFormatResetRelative:
    def test_none_returns_unknown(self):
        assert core.format_reset_relative(None) == "unknown"

    def test_empty_string_returns_unknown(self):
        assert core.format_reset_relative("") == "unknown"

    def test_malformed_string_returns_unknown(self):
        assert core.format_reset_relative("not-a-date") == "unknown"

    def test_valid_future_timestamp_starts_with_resets(self):
        # A timestamp far in the future — exact output is tz/now-dependent
        result = core.format_reset_relative("2099-12-31T23:59:59Z")
        assert result.startswith("resets")

    def test_past_timestamp_returns_resets_soon(self):
        result = core.format_reset_relative("2000-01-01T00:00:00Z")
        assert result == "resets soon"


# ---------------------------------------------------------------------------
# format_reset_absolute()
# ---------------------------------------------------------------------------

class TestFormatResetAbsolute:
    def test_none_returns_unknown(self):
        assert core.format_reset_absolute(None) == "unknown"

    def test_empty_string_returns_unknown(self):
        assert core.format_reset_absolute("") == "unknown"

    def test_malformed_string_returns_unknown(self):
        assert core.format_reset_absolute("garbage") == "unknown"

    def test_valid_timestamp_starts_with_resets(self):
        result = core.format_reset_absolute("2099-12-31T23:59:59Z")
        assert result.startswith("resets")


# ---------------------------------------------------------------------------
# find_plan_name()
# ---------------------------------------------------------------------------

class TestFindPlanName:
    def test_finds_plan_key(self):
        assert core.find_plan_name({"plan": "Pro"}) == "Pro"

    def test_finds_tier_key(self):
        assert core.find_plan_name({"tier": "Enterprise"}) == "Enterprise"

    def test_finds_subscription_key(self):
        assert core.find_plan_name({"subscription": "Business"}) == "Business"

    def test_returns_none_when_absent(self):
        assert core.find_plan_name({"something_else": "value"}) is None

    def test_ignores_non_string_values(self):
        assert core.find_plan_name({"plan": 42}) is None

    def test_ignores_empty_string_value(self):
        assert core.find_plan_name({"plan": ""}) is None

    def test_returns_none_for_empty_dict(self):
        assert core.find_plan_name({}) is None


# ---------------------------------------------------------------------------
# fetch_usage() — monkeypatched httpx
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


class TestFetchUsage:
    def test_200_ok_with_usage_data(self, monkeypatch):
        body = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 17, "resets_at": "2099-12-31T23:59:59Z"},
        }
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(200, body))
        result = core.fetch_usage("fake-token")

        assert result["ok"] is True
        assert result["session_pct"] == 40
        assert result["week_pct"] == 17
        assert result["status_code"] == 200

    def test_200_session_and_week_reset_raw_present(self, monkeypatch):
        body = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 17, "resets_at": "2099-12-30T00:00:00Z"},
        }
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(200, body))
        result = core.fetch_usage("fake-token")

        assert result["session_reset_raw"] == "2099-12-31T23:59:59Z"
        assert result["week_reset_raw"] == "2099-12-30T00:00:00Z"

    def test_401_returns_unauthorized(self, monkeypatch):
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(401))
        result = core.fetch_usage("fake-token")

        assert result["ok"] is False
        assert result["error"] == "unauthorized"
        assert result["status_code"] == 401

    def test_429_returns_rate_limited(self, monkeypatch):
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(429))
        result = core.fetch_usage("fake-token")

        assert result["ok"] is False
        assert result["error"] == "rate_limited"
        assert result["status_code"] == 429
        assert result["retry_after"] is None

    def test_429_with_retry_after_integer_header(self, monkeypatch):
        monkeypatch.setattr(
            core.httpx, "get",
            lambda *a, **kw: FakeResponse(429, headers={"Retry-After": "120"}),
        )
        result = core.fetch_usage("fake-token")

        assert result["ok"] is False
        assert result["error"] == "rate_limited"
        assert result["status_code"] == 429
        assert result["retry_after"] == 120

    def test_429_without_retry_after_header(self, monkeypatch):
        monkeypatch.setattr(
            core.httpx, "get",
            lambda *a, **kw: FakeResponse(429, headers={}),
        )
        result = core.fetch_usage("fake-token")

        assert result["ok"] is False
        assert result["status_code"] == 429
        assert result["retry_after"] is None

    def test_request_error_returns_ok_false_status_none(self, monkeypatch):
        def raise_request_error(*a, **kw):
            raise core.httpx.RequestError("connection failed")

        monkeypatch.setattr(core.httpx, "get", raise_request_error)
        result = core.fetch_usage("fake-token")

        assert result["ok"] is False
        assert result["status_code"] is None

    def test_non_200_non_401_non_429(self, monkeypatch):
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(500))
        result = core.fetch_usage("fake-token")

        assert result["ok"] is False
        assert "500" in result["error"]

    def test_sonnet_window_parsed_when_present(self, monkeypatch):
        body = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 17, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day_sonnet": {"utilization": 5, "resets_at": "2099-12-31T23:59:59Z"},
        }
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(200, body))
        result = core.fetch_usage("fake-token")

        assert result["sonnet_pct"] == 5

    def test_sonnet_window_absent_gives_none(self, monkeypatch):
        body = {
            "five_hour": {"utilization": 40, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 17, "resets_at": "2099-12-31T23:59:59Z"},
        }
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(200, body))
        result = core.fetch_usage("fake-token")

        assert result["sonnet_pct"] is None
        assert result["sonnet_reset_raw"] is None

    def test_result_never_contains_token(self, monkeypatch):
        body = {
            "five_hour": {"utilization": 10, "resets_at": "2099-12-31T23:59:59Z"},
            "seven_day": {"utilization": 20, "resets_at": "2099-12-31T23:59:59Z"},
        }
        secret = "super-secret-token-value"
        monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResponse(200, body))
        result = core.fetch_usage(secret)

        # Token must never appear in any result value
        for v in result.values():
            assert secret not in str(v)
