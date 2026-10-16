"""Behavioural tests for the three orders operations."""

from __future__ import annotations


def test_create_order_returns_201_with_generated_id(api, valid_order):
    response = api.post("/orders", json=valid_order)

    assert response.status_code == 201
    body = response.get_json()
    assert body["id"]
    assert body["status"] == "created"
    assert body["customer_tier"] == "premium"
    assert body["category"] == "electronics"
    assert body["amount"] == 149.99


def test_create_order_generates_a_different_id_per_order(api, valid_order):
    first = api.post("/orders", json=valid_order).get_json()["id"]
    second = api.post("/orders", json=valid_order).get_json()["id"]

    assert first != second


def test_get_order_returns_the_stored_order(api, valid_order):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]

    response = api.get(f"/orders/{order_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == order_id
    assert body["status"] == "created"
    assert body["category"] == "electronics"


def test_get_unknown_order_returns_404(api):
    response = api.get("/orders/ord_does_not_exist")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_cancel_order_returns_200_and_marks_it_cancelled(api, valid_order):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]

    response = api.post(f"/orders/{order_id}/cancel")

    assert response.status_code == 200
    assert response.get_json()["status"] == "cancelled"


def test_cancelled_order_stays_cancelled_when_read_back(api, valid_order):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]
    api.post(f"/orders/{order_id}/cancel")

    body = api.get(f"/orders/{order_id}").get_json()

    assert body["status"] == "cancelled"


def test_cancelling_twice_returns_409(api, valid_order):
    order_id = api.post("/orders", json=valid_order).get_json()["id"]
    api.post(f"/orders/{order_id}/cancel")

    response = api.post(f"/orders/{order_id}/cancel")

    assert response.status_code == 409
    assert response.get_json()["error"] == "conflict"


def test_cancelling_unknown_order_returns_404(api):
    response = api.post("/orders/ord_does_not_exist/cancel")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_unknown_path_returns_404(api):
    response = api.get("/invoices/42")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_listing_orders_is_not_supported_and_returns_404(api):
    response = api.get("/orders")

    assert response.status_code == 404


def test_create_order_accepts_a_trailing_slash(api, valid_order):
    response = api.post("/orders/", json=valid_order)

    assert response.status_code == 201
