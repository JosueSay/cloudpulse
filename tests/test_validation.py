"""Payload validation tests for ``POST /orders`` (HTTP 400 contract)."""

from __future__ import annotations

import pytest


def test_valid_payload_is_accepted(api, valid_order):
    assert api.post("/orders", json=valid_order).status_code == 201


@pytest.mark.parametrize("missing_field", ["customer_tier", "category", "amount"])
def test_missing_required_field_returns_400(api, valid_order, missing_field):
    payload = {k: v for k, v in valid_order.items() if k != missing_field}

    response = api.post("/orders", json=payload)

    assert response.status_code == 400
    body = response.get_json()
    assert body["error"] == "validation_error"
    assert any(missing_field in detail for detail in body["details"])


def test_unknown_customer_tier_returns_400(api, valid_order):
    response = api.post("/orders", json={**valid_order, "customer_tier": "platinum"})

    assert response.status_code == 400
    assert any("customer_tier" in detail for detail in response.get_json()["details"])


def test_unknown_category_returns_400(api, valid_order):
    response = api.post("/orders", json={**valid_order, "category": "spaceships"})

    assert response.status_code == 400
    assert any("category" in detail for detail in response.get_json()["details"])


@pytest.mark.parametrize("amount", [0, -1, -0.01])
def test_non_positive_amount_returns_400(api, valid_order, amount):
    response = api.post("/orders", json={**valid_order, "amount": amount})

    assert response.status_code == 400
    assert any("amount" in detail for detail in response.get_json()["details"])


@pytest.mark.parametrize("amount", ["149.99", None, [1], {"value": 1}])
def test_non_numeric_amount_returns_400(api, valid_order, amount):
    response = api.post("/orders", json={**valid_order, "amount": amount})

    assert response.status_code == 400


def test_boolean_amount_returns_400(api, valid_order):
    """``True`` is an ``int`` in Python; the schema must still reject it."""
    response = api.post("/orders", json={**valid_order, "amount": True})

    assert response.status_code == 400


def test_amount_above_the_maximum_returns_400(api, valid_order):
    response = api.post("/orders", json={**valid_order, "amount": 100_000.01})

    assert response.status_code == 400
    assert any("amount" in detail for detail in response.get_json()["details"])


def test_amount_at_the_maximum_is_accepted(api, valid_order):
    response = api.post("/orders", json={**valid_order, "amount": 100_000.0})

    assert response.status_code == 201


def test_unknown_field_returns_400(api, valid_order):
    response = api.post("/orders", json={**valid_order, "discount_code": "FREE"})

    assert response.status_code == 400
    assert any("discount_code" in detail for detail in response.get_json()["details"])


def test_malformed_json_body_returns_400(api):
    response = api.post(
        "/orders", data="{not valid json", content_type="application/json"
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_missing_body_returns_400(api):
    response = api.post("/orders")

    assert response.status_code == 400


def test_json_array_body_returns_400(api):
    response = api.post("/orders", json=[{"customer_tier": "free"}])

    assert response.status_code == 400


def test_validation_error_reports_every_invalid_field_at_once(api):
    response = api.post(
        "/orders", json={"customer_tier": "platinum", "category": "spaceships"}
    )

    assert response.status_code == 400
    details = response.get_json()["details"]
    assert any("customer_tier" in detail for detail in details)
    assert any("category" in detail for detail in details)
    assert any("amount" in detail for detail in details)
