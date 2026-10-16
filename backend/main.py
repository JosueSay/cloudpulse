"""CloudPulse orders API — observable serverless HTTP function.

A single Functions Framework HTTP entry point (``handle``) exposes three
operations backed by an in-memory store:

* ``POST /orders``              create an order
* ``GET  /orders/{id}``         read an order
* ``POST /orders/{id}/cancel``  cancel an order

Every request produces exactly one structured JSON event on stdout
(``message="request_completed"``) so Cloud Logging, log-based metrics and Log
Analytics SQL can analyse traffic, latency, errors and business attributes.

Two environment knobs shape the traffic experiment:

* ``FAILURE_RATE``     probability in ``[0, 1]`` of answering ``500``.
* ``EXTRA_LATENCY_MS`` artificial delay added to every request.

Both are read per request so the deployed service can be retuned by updating
the Cloud Run environment without a code change, and both are validated:
unparseable, non-finite or out-of-range values fall back to a safe default
instead of failing the request.

Storage caveat: ``_ORDERS`` lives in the memory of one Cloud Run instance.
Orders created on one instance are invisible to the others and are lost when an
instance is recycled, so a concurrent simulator must expect ``404`` for reads
and cancels routed to a different instance than the create.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import flask

# --- Domain schema ---------------------------------------------------------

CUSTOMER_TIERS = ("free", "standard", "premium")
CATEGORIES = ("electronics", "books", "grocery", "apparel")
MAX_AMOUNT = 100_000.0

STATUS_CREATED = "created"
STATUS_CANCELLED = "cancelled"

ORDER_FIELDS = ("customer_tier", "category", "amount")

# --- Runtime configuration -------------------------------------------------

FAILURE_RATE_VAR = "FAILURE_RATE"
EXTRA_LATENCY_VAR = "EXTRA_LATENCY_MS"

MAX_EXTRA_LATENCY_MS = 60_000.0

# --- Observability ---------------------------------------------------------

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_MAX_LENGTH = 64
_UNSAFE_REQUEST_ID_CHARS = re.compile(r"[^A-Za-z0-9._:-]")

LOG_MESSAGE = "request_completed"

ERROR_TYPE_NONE = "none"
ERROR_TYPE_SIMULATED = "simulated_failure"
ERROR_TYPE_UNHANDLED = "unhandled_exception"

OUTCOME_SUCCESS = "success"
OUTCOME_CLIENT_ERROR = "client_error"
OUTCOME_SERVER_ERROR = "server_error"

_SEVERITY_BY_OUTCOME = {
    OUTCOME_SUCCESS: "INFO",
    OUTCOME_CLIENT_ERROR: "WARNING",
    OUTCOME_SERVER_ERROR: "ERROR",
}

ENDPOINT_UNKNOWN = "unknown"
ENDPOINT_CREATE = "POST /orders"
ENDPOINT_READ = "GET /orders/{id}"
ENDPOINT_CANCEL = "POST /orders/{id}/cancel"

# --- Routing ---------------------------------------------------------------

_CREATE_ORDER = re.compile(r"^/orders/?$")
_CANCEL_ORDER = re.compile(r"^/orders/(?P<order_id>[^/]+)/cancel/?$")
_READ_ORDER = re.compile(r"^/orders/(?P<order_id>[^/]+)/?$")

# --- Storage ---------------------------------------------------------------

_ORDERS: dict[str, dict[str, Any]] = {}
_STORE_LOCK = threading.Lock()


class ApiError(Exception):
    """Business or protocol error mapped to an HTTP response and a log event."""

    def __init__(
        self,
        status_code: int,
        error: str,
        message: str,
        details: list[str] | None = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message
        self.details = details or []
        self.error_type = error_type or error

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.error, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class RequestContext:
    """Per-request correlation id, route label and business attributes."""

    request_id: str
    endpoint: str = ENDPOINT_UNKNOWN
    attributes: dict[str, Any] = field(default_factory=dict)

    def record_order(self, order: dict[str, Any]) -> None:
        self.attributes["order_id"] = order["id"]
        self.attributes["order_status"] = order["status"]
        for name in ORDER_FIELDS:
            self.attributes[name] = order[name]

    def record_submitted(self, body: Any) -> None:
        """Record the business attributes of a payload before validating it.

        Only values belonging to the schema are kept, so an arbitrary string
        sent by a client can never become a log-based metric label.
        """
        if not isinstance(body, dict):
            return
        for name, allowed in (
            ("customer_tier", CUSTOMER_TIERS),
            ("category", CATEGORIES),
        ):
            if body.get(name) in allowed:
                self.attributes[name] = body[name]
        if _is_number(body.get("amount")):
            self.attributes["amount"] = body["amount"]


# --- Configuration helpers -------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read a finite float from the environment, clamped to a safe range."""
    try:
        value = float(os.environ.get(name, "").strip())
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    return max(minimum, min(maximum, value))


def _now() -> str:
    return datetime.now(UTC).isoformat()


# --- Traffic shaping -------------------------------------------------------


def _apply_extra_latency() -> None:
    delay_ms = _env_float(EXTRA_LATENCY_VAR, 0.0, 0.0, MAX_EXTRA_LATENCY_MS)
    if delay_ms > 0:
        time.sleep(delay_ms / 1000)


def _maybe_simulate_failure() -> None:
    """Fail a configured share of requests before any state is mutated."""
    if random.random() < _env_float(FAILURE_RATE_VAR, 0.0, 0.0, 1.0):
        raise ApiError(
            500,
            "internal_error",
            "simulated server failure",
            error_type=ERROR_TYPE_SIMULATED,
        )


# --- Operations ------------------------------------------------------------


def _validate_order(body: Any) -> dict[str, Any]:
    """Validate a create-order payload, collecting every problem found."""
    if not isinstance(body, dict):
        raise ApiError(
            400,
            "validation_error",
            "request body must be a JSON object",
            ["body: expected a JSON object"],
        )

    details: list[str] = []

    for name, allowed in (
        ("customer_tier", CUSTOMER_TIERS),
        ("category", CATEGORIES),
    ):
        value = body.get(name)
        if value is None:
            details.append(f"{name}: is required")
        elif value not in allowed:
            details.append(f"{name}: must be one of {', '.join(allowed)}")

    amount = body.get("amount")
    if amount is None:
        details.append("amount: is required")
    elif not _is_number(amount):
        details.append("amount: must be a number")
    elif not 0 < amount <= MAX_AMOUNT:
        details.append(f"amount: must be greater than 0 and at most {MAX_AMOUNT}")

    details.extend(
        f"{name}: is not a recognised field"
        for name in sorted(set(body) - set(ORDER_FIELDS))
    )

    if details:
        raise ApiError(400, "validation_error", "invalid order payload", details)

    return {name: body[name] for name in ORDER_FIELDS}


def _read_json_body(request: flask.Request) -> Any:
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError(
            400,
            "validation_error",
            "request body must be a JSON object",
            ["body: expected a JSON object"],
        )
    return body


def _create_order(
    request: flask.Request, ctx: RequestContext
) -> tuple[dict[str, Any], int]:
    attributes = _validate_order(_read_json_body(request))

    timestamp = _now()
    order = {
        "id": f"ord_{uuid.uuid4().hex}",
        **attributes,
        "status": STATUS_CREATED,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with _STORE_LOCK:
        _ORDERS[order["id"]] = order
    ctx.record_order(order)
    return dict(order), 201


def _get_order(order_id: str, ctx: RequestContext) -> tuple[dict[str, Any], int]:
    with _STORE_LOCK:
        order = _ORDERS.get(order_id)
        snapshot = dict(order) if order else None
    if snapshot is None:
        raise ApiError(404, "not_found", f"order {order_id} does not exist")
    ctx.record_order(snapshot)
    return snapshot, 200


def _cancel_order(order_id: str, ctx: RequestContext) -> tuple[dict[str, Any], int]:
    """Cancel an order, serialising the read-modify-write under one lock.

    Holding the lock across the status check and the mutation is what makes two
    concurrent cancels resolve to exactly one ``200`` and one ``409``.
    """
    with _STORE_LOCK:
        order = _ORDERS.get(order_id)
        already_cancelled = order is not None and order["status"] == STATUS_CANCELLED
        if order is not None and not already_cancelled:
            order["status"] = STATUS_CANCELLED
            order["updated_at"] = _now()
        snapshot = dict(order) if order else None

    if snapshot is None:
        raise ApiError(404, "not_found", f"order {order_id} does not exist")

    ctx.record_order(snapshot)
    if already_cancelled:
        raise ApiError(409, "conflict", f"order {order_id} is already cancelled")
    return snapshot, 200


def _resolve_route(
    request: flask.Request, ctx: RequestContext
) -> Callable[[], tuple[dict[str, Any], int]]:
    """Label the route and return the action to run, without touching state."""
    path = request.path or "/"
    method = request.method

    if method == "POST" and _CREATE_ORDER.match(path):
        ctx.endpoint = ENDPOINT_CREATE
        # Recorded before validation so even a rejected request is analysable.
        ctx.record_submitted(request.get_json(silent=True))
        return lambda: _create_order(request, ctx)

    cancel = _CANCEL_ORDER.match(path)
    if cancel and method == "POST":
        ctx.endpoint = ENDPOINT_CANCEL
        order_id = cancel.group("order_id")
        ctx.attributes["order_id"] = order_id
        return lambda: _cancel_order(order_id, ctx)

    read = _READ_ORDER.match(path)
    if read and method == "GET":
        ctx.endpoint = ENDPOINT_READ
        order_id = read.group("order_id")
        ctx.attributes["order_id"] = order_id
        return lambda: _get_order(order_id, ctx)

    raise ApiError(404, "not_found", f"no route for {method} {path}")


# --- Logging ---------------------------------------------------------------


def _resolve_request_id(request: flask.Request) -> str:
    """Take the caller's correlation id, or mint one.

    The incoming value is stripped of anything outside ``[A-Za-z0-9._:-]`` and
    truncated, so a hostile header cannot inject characters into the log event
    or inflate metric label cardinality.
    """
    incoming = request.headers.get(REQUEST_ID_HEADER) or ""
    sanitized = _UNSAFE_REQUEST_ID_CHARS.sub("", incoming)[:REQUEST_ID_MAX_LENGTH]
    return sanitized or uuid.uuid4().hex


def _classify(status_code: int) -> str:
    if status_code >= 500:
        return OUTCOME_SERVER_ERROR
    if status_code >= 400:
        return OUTCOME_CLIENT_ERROR
    return OUTCOME_SUCCESS


def _emit_log(
    ctx: RequestContext,
    status_code: int,
    error_type: str,
    latency_ms: float,
    exception_type: str | None = None,
) -> None:
    """Write the single structured event that closes the request.

    Only the fields below are serialised. Request headers, request bodies and
    the environment are never logged, so credentials cannot reach Cloud
    Logging; an unhandled error contributes its exception class name only,
    never its message.
    """
    outcome = _classify(status_code)
    event: dict[str, Any] = {
        "severity": _SEVERITY_BY_OUTCOME[outcome],
        "message": LOG_MESSAGE,
        "request_id": ctx.request_id,
        "endpoint": ctx.endpoint,
        "status_code": status_code,
        "outcome": outcome,
        "error_type": error_type,
        "latency_ms": round(latency_ms, 3),
        "customer_tier": ctx.attributes.get("customer_tier"),
        "category": ctx.attributes.get("category"),
        "amount": ctx.attributes.get("amount"),
        "order_id": ctx.attributes.get("order_id"),
        "order_status": ctx.attributes.get("order_status"),
    }
    if exception_type is not None:
        event["exception_type"] = exception_type
    print(json.dumps(event), file=sys.stdout, flush=True)


def handle(request: flask.Request) -> flask.Response:
    """Functions Framework HTTP entry point."""
    started = time.perf_counter()
    ctx = RequestContext(request_id=_resolve_request_id(request))
    exception_type: str | None = None

    try:
        _apply_extra_latency()
        action = _resolve_route(request, ctx)
        _maybe_simulate_failure()
        payload, status_code = action()
        error_type = ERROR_TYPE_NONE
    except ApiError as error:
        payload = error.to_payload()
        status_code = error.status_code
        error_type = error.error_type
    except Exception as error:  # noqa: BLE001 - never let a bug skip the log
        exception_type = type(error).__name__
        payload = {"error": "internal_error", "message": "internal server error"}
        status_code = 500
        error_type = ERROR_TYPE_UNHANDLED

    response = flask.jsonify(payload)
    response.status_code = status_code
    response.headers[REQUEST_ID_HEADER] = ctx.request_id

    _emit_log(
        ctx,
        status_code,
        error_type,
        (time.perf_counter() - started) * 1000,
        exception_type,
    )
    return response
