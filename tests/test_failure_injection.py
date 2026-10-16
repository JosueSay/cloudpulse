"""FAILURE_RATE, EXTRA_LATENCY_MS and unhandled-error behaviour."""

from __future__ import annotations

import time

import pytest

# --- Simulated server failures (FAILURE_RATE) ------------------------------


def test_failure_rate_zero_never_returns_500(api, valid_order, monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "0")

    statuses = {api.post("/orders", json=valid_order).status_code for _ in range(25)}

    assert statuses == {201}


def test_unset_failure_rate_never_returns_500(api, valid_order):
    statuses = {api.post("/orders", json=valid_order).status_code for _ in range(10)}

    assert statuses == {201}


def test_failure_rate_one_always_returns_500(api, valid_order, monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "1")

    statuses = {api.post("/orders", json=valid_order).status_code for _ in range(10)}

    assert statuses == {500}


def test_simulated_failure_body_reports_an_internal_error(
    api, valid_order, monkeypatch
):
    monkeypatch.setenv("FAILURE_RATE", "1")

    response = api.post("/orders", json=valid_order)

    assert response.get_json()["error"] == "internal_error"


def test_simulated_failure_is_logged_as_a_server_error(
    api, valid_order, monkeypatch, read_events
):
    monkeypatch.setenv("FAILURE_RATE", "1")

    api.post("/orders", json=valid_order)

    event = read_events()[0]
    assert event["status_code"] == 500
    assert event["outcome"] == "server_error"
    assert event["severity"] == "ERROR"
    assert event["error_type"] == "simulated_failure"


def test_simulated_failure_keeps_the_endpoint_and_business_attributes(
    api, valid_order, monkeypatch, read_events
):
    monkeypatch.setenv("FAILURE_RATE", "1")

    api.post("/orders", json=valid_order)

    event = read_events()[0]
    assert event["endpoint"] == "POST /orders"
    assert event["customer_tier"] == "premium"
    assert event["category"] == "electronics"


def test_simulated_failure_echoes_the_request_id(api, valid_order, monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "1")

    response = api.post(
        "/orders", json=valid_order, headers={"X-Request-ID": "sim-000500"}
    )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "sim-000500"


def test_simulated_failure_applies_to_reads(api, valid_order, monkeypatch):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]

    monkeypatch.setenv("FAILURE_RATE", "1")

    assert api.get(f"/orders/{order_id}").status_code == 500


def test_simulated_failure_does_not_cancel_the_order(api, valid_order, monkeypatch):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]

    monkeypatch.setenv("FAILURE_RATE", "1")
    assert api.post(f"/orders/{order_id}/cancel").status_code == 500

    monkeypatch.setenv("FAILURE_RATE", "0")
    assert api.get(f"/orders/{order_id}").get_json()["status"] == "created"


def test_simulated_failure_does_not_store_the_order(api, valid_order, monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "1")
    api.post("/orders", json=valid_order)

    monkeypatch.setenv("FAILURE_RATE", "0")
    second = api.post("/orders", json=valid_order).get_json()["id"]

    assert api.get(f"/orders/{second}").status_code == 200


def test_failure_rate_above_one_is_clamped_to_always_failing(
    api, valid_order, monkeypatch
):
    monkeypatch.setenv("FAILURE_RATE", "5")

    assert api.post("/orders", json=valid_order).status_code == 500


def test_negative_failure_rate_is_clamped_to_never_failing(
    api, valid_order, monkeypatch
):
    monkeypatch.setenv("FAILURE_RATE", "-1")

    assert api.post("/orders", json=valid_order).status_code == 201


@pytest.mark.parametrize("raw_value", ["abc", "", "  ", "nan", "inf"])
def test_unparseable_failure_rate_is_ignored(api, valid_order, monkeypatch, raw_value):
    monkeypatch.setenv("FAILURE_RATE", raw_value)

    assert api.post("/orders", json=valid_order).status_code == 201


# --- Artificial latency (EXTRA_LATENCY_MS) --------------------------------


def test_extra_latency_delays_the_response(api, valid_order, monkeypatch, read_events):
    monkeypatch.setenv("EXTRA_LATENCY_MS", "150")

    started = time.perf_counter()
    response = api.post("/orders", json=valid_order)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 201
    assert elapsed_ms >= 150
    assert read_events()[0]["latency_ms"] >= 150


def test_extra_latency_also_delays_error_responses(api, monkeypatch):
    monkeypatch.setenv("EXTRA_LATENCY_MS", "150")

    started = time.perf_counter()
    response = api.get("/orders/ord_missing")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 404
    assert elapsed_ms >= 150


def test_zero_extra_latency_is_not_delayed(api, valid_order, monkeypatch):
    monkeypatch.setenv("EXTRA_LATENCY_MS", "0")

    started = time.perf_counter()
    api.post("/orders", json=valid_order)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 150


@pytest.mark.parametrize("raw_value", ["abc", "", "-50", "nan", "inf"])
def test_invalid_extra_latency_is_ignored(api, valid_order, monkeypatch, raw_value):
    monkeypatch.setenv("EXTRA_LATENCY_MS", raw_value)

    started = time.perf_counter()
    response = api.post("/orders", json=valid_order)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 201
    assert elapsed_ms < 150


def test_extra_latency_is_capped(api, valid_order, monkeypatch, backend_module):
    """A mistyped EXTRA_LATENCY_MS must not hold a billed request open."""
    monkeypatch.setattr(backend_module, "MAX_EXTRA_LATENCY_MS", 10)
    monkeypatch.setenv("EXTRA_LATENCY_MS", "600000")

    started = time.perf_counter()
    response = api.post("/orders", json=valid_order)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 201
    assert elapsed_ms < 150


# --- Unhandled errors -----------------------------------------------------


def _boom(*_args, **_kwargs):
    raise RuntimeError("connection failed for user=svc password=hunter2")


def test_unhandled_exception_returns_500(api, valid_order, backend_module, monkeypatch):
    monkeypatch.setattr(backend_module, "_resolve_route", _boom)

    response = api.post("/orders", json=valid_order)

    assert response.status_code == 500
    assert response.get_json()["error"] == "internal_error"


def test_unhandled_exception_still_emits_one_log_event(
    api, valid_order, backend_module, monkeypatch, read_events
):
    monkeypatch.setattr(backend_module, "_resolve_route", _boom)

    api.post("/orders", json=valid_order)

    events = read_events()
    assert len(events) == 1
    assert events[0]["outcome"] == "server_error"
    assert events[0]["severity"] == "ERROR"
    assert events[0]["error_type"] == "unhandled_exception"
    assert events[0]["exception_type"] == "RuntimeError"


def test_unhandled_exception_does_not_leak_its_message(
    api, valid_order, backend_module, monkeypatch, capsys
):
    monkeypatch.setattr(backend_module, "_resolve_route", _boom)

    response = api.post("/orders", json=valid_order)

    assert "hunter2" not in response.get_data(as_text=True)
    assert "hunter2" not in capsys.readouterr().out
