"""Structured logging contract consumed by Cloud Logging, log-based metrics
and Log Analytics SQL."""

from __future__ import annotations

import pytest

REQUIRED_FIELDS = (
    "severity",
    "message",
    "request_id",
    "endpoint",
    "status_code",
    "outcome",
    "error_type",
    "latency_ms",
)


def test_one_request_emits_exactly_one_log_event(api, valid_order, read_events):
    api.post("/orders", json=valid_order)

    assert len(read_events()) == 1


def test_three_requests_emit_three_log_events(api, valid_order, read_events):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]
    api.get(f"/orders/{order_id}")
    api.post(f"/orders/{order_id}/cancel")

    assert len(read_events()) == 3


def test_log_event_carries_every_required_field(api, valid_order, read_events):
    api.post("/orders", json=valid_order)

    event = read_events()[0]

    missing = [field for field in REQUIRED_FIELDS if field not in event]
    assert missing == []
    assert event["message"] == "request_completed"


def test_log_event_carries_business_attributes_on_create(api, valid_order, read_events):
    api.post("/orders", json=valid_order)

    event = read_events()[0]

    assert event["customer_tier"] == "premium"
    assert event["category"] == "electronics"
    assert event["amount"] == 149.99


def test_log_event_carries_business_attributes_of_the_stored_order_on_read(
    api, valid_order, read_events
):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]
    read_events()

    api.get(f"/orders/{order_id}")

    event = read_events()[0]
    assert event["order_id"] == order_id
    assert event["customer_tier"] == "premium"
    assert event["order_status"] == "created"


def test_log_event_keeps_known_business_attributes_on_validation_error(
    api, read_events
):
    api.post(
        "/orders",
        json={"customer_tier": "premium", "category": "electronics", "amount": -5},
    )

    event = read_events()[0]

    assert event["customer_tier"] == "premium"
    assert event["category"] == "electronics"


def test_successful_request_is_classified_as_success(api, valid_order, read_events):
    api.post("/orders", json=valid_order)

    event = read_events()[0]

    assert event["status_code"] == 201
    assert event["outcome"] == "success"
    assert event["severity"] == "INFO"
    assert event["error_type"] == "none"


@pytest.mark.parametrize(
    ("payload", "expected_error_type"),
    [
        ({"customer_tier": "platinum"}, "validation_error"),
    ],
)
def test_validation_error_is_classified_as_client_error(
    api, read_events, payload, expected_error_type
):
    api.post("/orders", json=payload)

    event = read_events()[0]

    assert event["status_code"] == 400
    assert event["outcome"] == "client_error"
    assert event["severity"] == "WARNING"
    assert event["error_type"] == expected_error_type


def test_not_found_is_classified_as_client_error(api, read_events):
    api.get("/orders/ord_missing")

    event = read_events()[0]

    assert event["status_code"] == 404
    assert event["outcome"] == "client_error"
    assert event["severity"] == "WARNING"
    assert event["error_type"] == "not_found"


def test_conflict_is_classified_as_client_error(api, valid_order, read_events):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]
    api.post(f"/orders/{order_id}/cancel")
    read_events()

    api.post(f"/orders/{order_id}/cancel")

    event = read_events()[0]
    assert event["status_code"] == 409
    assert event["outcome"] == "client_error"
    assert event["severity"] == "WARNING"
    assert event["error_type"] == "conflict"


def test_endpoint_label_uses_the_route_template_not_the_order_id(
    api, valid_order, read_events
):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]
    read_events()

    api.get(f"/orders/{order_id}")
    assert read_events()[0]["endpoint"] == "GET /orders/{id}"

    api.post(f"/orders/{order_id}/cancel")
    assert read_events()[0]["endpoint"] == "POST /orders/{id}/cancel"


def test_create_endpoint_label_is_the_collection_route(api, valid_order, read_events):
    api.post("/orders", json=valid_order)

    assert read_events()[0]["endpoint"] == "POST /orders"


def test_unrouted_request_is_logged_with_an_unknown_endpoint(api, read_events):
    api.get("/invoices/42")

    event = read_events()[0]

    assert event["endpoint"] == "unknown"
    assert event["status_code"] == 404


def test_incoming_request_id_is_echoed_and_logged(api, valid_order, read_events):
    response = api.post(
        "/orders", json=valid_order, headers={"X-Request-ID": "sim-000042"}
    )

    assert response.headers["X-Request-ID"] == "sim-000042"
    assert read_events()[0]["request_id"] == "sim-000042"


def test_request_id_is_generated_when_the_header_is_absent(
    api, valid_order, read_events
):
    response = api.post("/orders", json=valid_order)

    generated = response.headers["X-Request-ID"]
    assert generated
    assert read_events()[0]["request_id"] == generated


def test_generated_request_ids_differ_between_requests(api, valid_order, read_events):
    first = api.post("/orders", json=valid_order).headers["X-Request-ID"]
    second = api.post("/orders", json=valid_order).headers["X-Request-ID"]

    assert first != second


def test_request_id_is_echoed_on_error_responses(api, read_events):
    response = api.get("/orders/ord_missing", headers={"X-Request-ID": "sim-000007"})

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "sim-000007"
    assert read_events()[0]["request_id"] == "sim-000007"


def test_latency_ms_is_recorded_as_a_non_negative_number(api, valid_order, read_events):
    api.post("/orders", json=valid_order)

    latency = read_events()[0]["latency_ms"]

    assert isinstance(latency, (int, float))
    assert latency >= 0


def test_authorization_header_is_never_logged(api, valid_order, capsys):
    api.post(
        "/orders",
        json=valid_order,
        headers={"Authorization": "Bearer super-secret-token"},
    )

    assert "super-secret-token" not in capsys.readouterr().out


def test_unsafe_characters_in_the_request_id_are_stripped(
    api, valid_order, read_events
):
    response = api.post(
        "/orders",
        json=valid_order,
        headers={"X-Request-ID": "sim 42 <script>alert(1)</script>"},
    )

    logged = read_events()[0]["request_id"]
    assert logged == response.headers["X-Request-ID"]
    assert logged == "sim42scriptalert1script"


def test_request_id_made_only_of_unsafe_characters_is_replaced(
    api, valid_order, read_events
):
    response = api.post("/orders", json=valid_order, headers={"X-Request-ID": "<<>>"})

    logged = read_events()[0]["request_id"]
    assert logged
    assert logged == response.headers["X-Request-ID"]
    assert "<" not in logged


def test_overlong_request_id_is_truncated(api, valid_order, read_events):
    response = api.post(
        "/orders", json=valid_order, headers={"X-Request-ID": "x" * 300}
    )

    logged = read_events()[0]["request_id"]
    assert len(logged) == 64
    assert response.headers["X-Request-ID"] == logged
