"""CloudPulse traffic simulator — a bell-shaped HTTP load against the orders API.

The simulator turns ``simulator/config.json`` into one deterministic plan and
then executes it:

1. ``build_plan`` draws ``n_requests`` arrival instants from ``N(mu, sigma)``
   expressed in minutes, clips them to ``[0, duration_min]`` and sorts them.
   Every other decision of a request (operation, segment, whether it is meant
   to fail) is drawn from the same seeded generator, so a plan is reproducible
   from ``(config, run_id)`` alone and can be inspected before any traffic is
   sent (``--dry-run``).
2. ``dispatch`` fires each request at its instant without waiting for the
   previous response: one ``asyncio`` task per request over a single
   ``httpx.AsyncClient`` whose connection pool is capped by
   ``max_connections``, so 6.000 requests never become 6.000 sockets.
3. Every attempt appends one row to ``requests.csv`` — including connection
   failures and timeouts, which carry an empty ``status_code`` instead of
   disappearing.

The CSV records what the simulator *intended* (``intended_event``,
``expected_status``) next to what the API actually answered (``status_code``),
which is what makes intentional client errors distinguishable from the ``500``
responses produced by the backend.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

import httpx
import numpy as np

# --- API contract mirror ---------------------------------------------------
# Kept in sync by hand with backend/main.py: the simulator is a client, so it
# must not import the function module.

CUSTOMER_TIERS = ("free", "standard", "premium")
CATEGORIES = ("electronics", "books", "grocery", "apparel")

MIN_AMOUNT = 5.0
MAX_AMOUNT = 500.0

REQUEST_ID_HEADER = "X-Request-ID"

OPERATION_CREATE = "create"
OPERATION_READ = "read"
OPERATION_CANCEL = "cancel"
OPERATIONS = (OPERATION_CREATE, OPERATION_READ, OPERATION_CANCEL)

# --- Scenarios -------------------------------------------------------------

# An identity token from `gcloud auth print-identity-token` lives about an hour
# and the official run lasts exactly 60 minutes, so a token fetched once at
# startup expires before the last request. Renewing every 30 minutes keeps the
# token in use at most half its life.
DEFAULT_TOKEN_REFRESH_S = 1800.0
TOKEN_LIFETIME_S = 3600.0

EFFECT_DOUBLE_ERRORS = "double_errors"
EFFECT_MULTIPLIERS = {EFFECT_DOUBLE_ERRORS: 2.0}


class ConfigError(ValueError):
    """The configuration file cannot produce the requested experiment."""


@dataclass(frozen=True)
class Scenario:
    """A time window that changes the behaviour of one traffic segment."""

    start_min: float
    end_min: float
    effect: str
    category: str

    @property
    def multiplier(self) -> float:
        return EFFECT_MULTIPLIERS[self.effect]

    def matches(self, minute: float, category: str) -> bool:
        """Whether a request belongs to this scenario.

        The window is half-open so that adjacent scenarios cannot both claim
        the same minute.
        """
        return category == self.category and self.start_min <= minute < self.end_min


@dataclass(frozen=True)
class SimulatorConfig:
    """Validated experiment parameters."""

    target_url: str
    n_requests: int
    mu_min: float
    sigma_min: float
    invalid_share: float
    seed: int
    duration_min: float
    seconds_per_minute: float
    operation_mix: tuple[tuple[str, float], ...]
    output_csv: Path
    timeout_s: float
    max_connections: int
    token_refresh_s: float
    scenarios: tuple[Scenario, ...]
    quick_overrides: tuple[tuple[str, Any], ...] = ()

    # --- Derived values ---

    @property
    def duration_seconds(self) -> float:
        """Wall-clock length of the run."""
        return self.duration_min * self.seconds_per_minute

    @property
    def operation_weights(self) -> tuple[float, ...]:
        """Weights in ``OPERATIONS`` order, for the plan generator."""
        mix = dict(self.operation_mix)
        return tuple(mix[name] for name in OPERATIONS)

    def error_probability(self, minute: float, category: str) -> float:
        """Probability that a request in this segment is sent broken on purpose.

        Scenario multipliers compose, and the result is capped at ``1.0`` so a
        generous ``invalid_share`` can never ask for more than every request.
        """
        probability = self.invalid_share
        for scenario in self.scenarios:
            if scenario.matches(minute, category):
                probability *= scenario.multiplier
        return min(1.0, probability)

    def scenario_at(self, minute: float, category: str) -> Scenario | None:
        """The first scenario covering this segment, for CSV annotation."""
        for scenario in self.scenarios:
            if scenario.matches(minute, category):
                return scenario
        return None

    # --- Derived configurations ---

    def with_overrides(self, **overrides: Any) -> SimulatorConfig:
        """A re-validated copy of this configuration."""
        unknown = sorted(set(overrides) - set(_OVERRIDABLE_FIELDS))
        if unknown:
            raise ConfigError(f"unknown configuration override: {', '.join(unknown)}")
        return _validated(replace(self, **overrides))

    def for_quick_run(self) -> SimulatorConfig:
        """The small, seconds-long variant declared under ``quick``."""
        return self.with_overrides(**dict(self.quick_overrides))


_REQUIRED_KEYS = frozenset(
    {
        "target_url",
        "n_requests",
        "mu_min",
        "sigma_min",
        "invalid_share",
        "seed",
        "duration_min",
        "seconds_per_minute",
        "operation_mix",
        "output_csv",
        "timeout_s",
        "max_connections",
        "scenarios",
    }
)
_OPTIONAL_KEYS = frozenset({"quick", "token_refresh_s"})
_SCENARIO_KEYS = frozenset({"start_min", "end_min", "effect", "category"})

# ``output_csv`` is excluded on purpose: a relative path can only be resolved
# against the configuration file it came from.
_OVERRIDABLE_FIELDS = frozenset(
    {
        "target_url",
        "n_requests",
        "mu_min",
        "sigma_min",
        "invalid_share",
        "seed",
        "duration_min",
        "seconds_per_minute",
        "timeout_s",
        "max_connections",
        "output_csv",
        "scenarios",
        "token_refresh_s",
    }
)


def _require_number(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key}: must be a number")
    if not math.isfinite(value):
        raise ConfigError(f"{key}: must be finite")
    return float(value)


def _require_positive(value: Any, key: str) -> float:
    number = _require_number(value, key)
    if number <= 0:
        raise ConfigError(f"{key}: must be greater than 0")
    return number


def _require_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key}: must be an integer")
    return value


def _parse_scenarios(raw: Any, duration_min: float) -> tuple[Scenario, ...]:
    if not isinstance(raw, list):
        raise ConfigError("scenarios: must be a list")

    scenarios: list[Scenario] = []
    for position, item in enumerate(raw):
        label = f"scenarios[{position}]"
        if not isinstance(item, dict):
            raise ConfigError(f"{label}: must be an object")
        missing = sorted(_SCENARIO_KEYS - set(item))
        if missing:
            raise ConfigError(f"{label}: missing {', '.join(missing)}")
        unknown = sorted(set(item) - _SCENARIO_KEYS)
        if unknown:
            raise ConfigError(f"{label}: unknown key {', '.join(unknown)}")

        start = _require_number(item["start_min"], f"{label}.start_min")
        end = _require_number(item["end_min"], f"{label}.end_min")
        if start < 0:
            raise ConfigError(f"{label}.start_min: must not be negative")
        if end > duration_min:
            raise ConfigError(f"{label}.end_min: must not exceed duration_min")
        if start >= end:
            raise ConfigError(f"{label}.start_min: must be before end_min")

        effect = item["effect"]
        if effect not in EFFECT_MULTIPLIERS:
            raise ConfigError(f"{label}.effect: unknown effect {effect!r}")
        category = item["category"]
        if category not in CATEGORIES:
            raise ConfigError(f"{label}.category: unknown category {category!r}")

        scenarios.append(Scenario(start, end, effect, category))
    return tuple(scenarios)


def _parse_operation_mix(raw: Any) -> tuple[tuple[str, float], ...]:
    if not isinstance(raw, dict):
        raise ConfigError("operation_mix: must be an object")
    unknown = sorted(set(raw) - set(OPERATIONS))
    if unknown:
        raise ConfigError(f"operation_mix: unknown operation {', '.join(unknown)}")
    missing = sorted(set(OPERATIONS) - set(raw))
    if missing:
        raise ConfigError(f"operation_mix: missing {', '.join(missing)}")

    mix = {}
    for name in OPERATIONS:
        weight = _require_number(raw[name], f"operation_mix.{name}")
        if weight < 0:
            raise ConfigError(f"operation_mix.{name}: must not be negative")
        mix[name] = weight
    if not math.isclose(sum(mix.values()), 1.0, abs_tol=1e-9):
        raise ConfigError("operation_mix: weights must sum to 1")
    return tuple(mix.items())


def _validated(config: SimulatorConfig) -> SimulatorConfig:
    """Re-check every invariant after construction or an override."""
    if not str(config.target_url).startswith(("http://", "https://")):
        raise ConfigError("target_url: must start with http:// or https://")

    if _require_int(config.n_requests, "n_requests") <= 0:
        raise ConfigError("n_requests: must be greater than 0")
    _require_int(config.seed, "seed")
    if config.seed < 0:
        raise ConfigError("seed: must not be negative")

    duration = _require_positive(config.duration_min, "duration_min")
    _require_positive(config.sigma_min, "sigma_min")
    _require_positive(config.seconds_per_minute, "seconds_per_minute")
    _require_positive(config.timeout_s, "timeout_s")
    _require_positive(config.token_refresh_s, "token_refresh_s")
    if _require_int(config.max_connections, "max_connections") <= 0:
        raise ConfigError("max_connections: must be greater than 0")

    mu = _require_number(config.mu_min, "mu_min")
    if not 0 <= mu <= duration:
        raise ConfigError("mu_min: must fall inside [0, duration_min]")

    share = _require_number(config.invalid_share, "invalid_share")
    if not 0 <= share <= 1:
        raise ConfigError("invalid_share: must fall inside [0, 1]")

    for scenario in config.scenarios:
        if not isinstance(scenario, Scenario):
            raise ConfigError("scenarios: must be Scenario instances")
        if scenario.end_min > duration:
            raise ConfigError("scenarios: end_min must not exceed duration_min")
    return config


def parse_config(data: Any, base_dir: Path) -> SimulatorConfig:
    """Build a validated configuration from parsed JSON.

    ``base_dir`` resolves a relative ``output_csv``, so the configuration file
    can be moved without rewriting the path inside it.
    """
    if not isinstance(data, dict):
        raise ConfigError("configuration: must be a JSON object")

    missing = sorted(_REQUIRED_KEYS - set(data))
    if missing:
        raise ConfigError(f"configuration: missing {', '.join(missing)}")
    unknown = sorted(set(data) - _REQUIRED_KEYS - _OPTIONAL_KEYS)
    if unknown:
        raise ConfigError(f"configuration: unknown key {', '.join(unknown)}")

    quick = data.get("quick", {})
    if not isinstance(quick, dict):
        raise ConfigError("quick: must be an object")
    unknown_quick = sorted(set(quick) - _OVERRIDABLE_FIELDS)
    if unknown_quick:
        raise ConfigError(f"quick: unknown override {', '.join(unknown_quick)}")

    duration = _require_positive(data["duration_min"], "duration_min")
    output = Path(str(data["output_csv"])).expanduser()
    config = SimulatorConfig(
        target_url=str(data["target_url"]),
        n_requests=data["n_requests"],
        mu_min=data["mu_min"],
        sigma_min=data["sigma_min"],
        invalid_share=data["invalid_share"],
        seed=data["seed"],
        duration_min=data["duration_min"],
        seconds_per_minute=data["seconds_per_minute"],
        operation_mix=_parse_operation_mix(data["operation_mix"]),
        output_csv=output if output.is_absolute() else (base_dir / output).resolve(),
        timeout_s=data["timeout_s"],
        max_connections=data["max_connections"],
        token_refresh_s=data.get("token_refresh_s", DEFAULT_TOKEN_REFRESH_S),
        scenarios=_parse_scenarios(data["scenarios"], duration),
        quick_overrides=tuple(quick.items()),
    )
    return _validated(config)


def load_config(path: Path | str) -> SimulatorConfig:
    """Read and validate a configuration file."""
    path = Path(path)
    try:
        raw = path.read_text()
    except OSError as error:
        raise ConfigError(f"configuration file not found: {path}") from error
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigError(f"configuration file is not valid JSON: {path}") from error
    return parse_config(data, path.resolve().parent)


# --- Planned traffic -------------------------------------------------------

INTENT_VALID = "valid"
INTENT_INVALID = "invalid"

EVENT_CREATE_VALID = "create_valid"
EVENT_CREATE_INVALID_PAYLOAD = "create_invalid_payload"
EVENT_READ_VALID = "read_valid"
EVENT_READ_MISSING = "read_missing_order"
EVENT_CANCEL_VALID = "cancel_valid"
EVENT_CANCEL_MISSING = "cancel_missing_order"
EVENT_CANCEL_ALREADY_CANCELLED = "cancel_already_cancelled"

# The status each intended event asks the phase 1 API for. The three error
# codes of the laboratory are reached on purpose: 400 through a broken payload,
# 404 through an unknown identifier and 409 through an impossible sequence.
EVENT_EXPECTED_STATUS = {
    EVENT_CREATE_VALID: 201,
    EVENT_CREATE_INVALID_PAYLOAD: 400,
    EVENT_READ_VALID: 200,
    EVENT_READ_MISSING: 404,
    EVENT_CANCEL_VALID: 200,
    EVENT_CANCEL_MISSING: 404,
    EVENT_CANCEL_ALREADY_CANCELLED: 409,
}

VALID_EVENT_BY_OPERATION = {
    OPERATION_CREATE: EVENT_CREATE_VALID,
    OPERATION_READ: EVENT_READ_VALID,
    OPERATION_CANCEL: EVENT_CANCEL_VALID,
}

# Ways to break a create payload, one per rule of the API schema.
FLAW_MISSING_AMOUNT = "missing_amount"
FLAW_UNKNOWN_FIELD = "unknown_field"
FLAW_BAD_CATEGORY = "bad_category"
FLAW_NEGATIVE_AMOUNT = "negative_amount"
FLAW_AMOUNT_NOT_A_NUMBER = "amount_not_a_number"
FLAW_NOT_AN_OBJECT = "not_an_object"

PAYLOAD_FLAWS = (
    FLAW_MISSING_AMOUNT,
    FLAW_UNKNOWN_FIELD,
    FLAW_BAD_CATEGORY,
    FLAW_NEGATIVE_AMOUNT,
    FLAW_AMOUNT_NOT_A_NUMBER,
    FLAW_NOT_AN_OBJECT,
)

UNKNOWN_CATEGORY = "furniture"


@dataclass(frozen=True)
class PlannedRequest:
    """One request decided before the run starts.

    Everything here is a function of ``(config, run_id)``: the instant, the
    operation, the segment and whether the request is meant to be rejected.
    What cannot be known in advance — which order identifier it will touch —
    is resolved at send time from the orders created during the run.
    """

    index: int
    run_id: str
    request_id: str
    scheduled_min: float
    operation: str
    intended_event: str
    intent: str
    expected_status: int
    category: str
    customer_tier: str
    amount: float
    payload_flaw: str
    scenario: str

    def due_seconds(self, seconds_per_minute: float) -> float:
        """Offset from the start of the run, in wall-clock seconds."""
        return self.scheduled_min * seconds_per_minute


def order_payload(planned: PlannedRequest) -> Any:
    """The JSON body to send, or ``None`` for a request without one.

    A valid create carries exactly the three schema fields; a broken one
    carries the single flaw the plan assigned to it, so the ``400`` it earns is
    attributable to a known cause.
    """
    if planned.operation != OPERATION_CREATE:
        return None

    body: dict[str, Any] = {
        "customer_tier": planned.customer_tier,
        "category": planned.category,
        "amount": planned.amount,
    }
    flaw = planned.payload_flaw
    if not flaw:
        return body
    if flaw == FLAW_MISSING_AMOUNT:
        del body["amount"]
    elif flaw == FLAW_UNKNOWN_FIELD:
        body["discount"] = 10
    elif flaw == FLAW_BAD_CATEGORY:
        body["category"] = UNKNOWN_CATEGORY
    elif flaw == FLAW_NEGATIVE_AMOUNT:
        body["amount"] = -abs(planned.amount)
    elif flaw == FLAW_AMOUNT_NOT_A_NUMBER:
        body["amount"] = "many"
    elif flaw == FLAW_NOT_AN_OBJECT:
        return [body]
    else:  # pragma: no cover - guarded by PAYLOAD_FLAWS
        raise ValueError(f"unknown payload flaw: {flaw}")
    return body


def _invalid_event(operation: str, variant_draw: float) -> str:
    """Pick how a request of this operation is going to be rejected."""
    if operation == OPERATION_CREATE:
        return EVENT_CREATE_INVALID_PAYLOAD
    if operation == OPERATION_READ:
        return EVENT_READ_MISSING
    # A cancel can fail two ways; split them evenly so both the unknown
    # identifier and the impossible sequence are exercised.
    return (
        EVENT_CANCEL_MISSING if variant_draw < 0.5 else EVENT_CANCEL_ALREADY_CANCELLED
    )


def build_plan(config: SimulatorConfig, run_id: str) -> tuple[PlannedRequest, ...]:
    """Draw the whole experiment from one seeded generator.

    Arrival instants come from ``N(mu_min, sigma_min)`` clipped to
    ``[0, duration_min]`` — clipped, not resampled, so the plan keeps exactly
    one draw per request and exactly ``n_requests`` rows. The price is a small
    pile-up at both bounds (about 0.13 % of the traffic per tail with the
    laboratory values).
    """
    rng = np.random.default_rng(config.seed)
    total = config.n_requests

    minutes = np.sort(
        np.clip(
            rng.normal(config.mu_min, config.sigma_min, total),
            0.0,
            config.duration_min,
        )
    )
    categories = rng.integers(0, len(CATEGORIES), total)
    tiers = rng.integers(0, len(CUSTOMER_TIERS), total)
    amounts = np.round(rng.uniform(MIN_AMOUNT, MAX_AMOUNT, total), 2)
    operations = rng.choice(
        len(OPERATIONS), size=total, p=np.asarray(config.operation_weights)
    )
    error_draws = rng.random(total)
    variant_draws = rng.random(total)
    flaws = rng.integers(0, len(PAYLOAD_FLAWS), total)

    plan: list[PlannedRequest] = []
    for index in range(total):
        minute = float(minutes[index])
        category = CATEGORIES[int(categories[index])]
        operation = OPERATIONS[int(operations[index])]

        scenario = config.scenario_at(minute, category)
        invalid = error_draws[index] < config.error_probability(minute, category)
        if invalid:
            event = _invalid_event(operation, float(variant_draws[index]))
            flaw = (
                PAYLOAD_FLAWS[int(flaws[index])]
                if event == EVENT_CREATE_INVALID_PAYLOAD
                else ""
            )
        else:
            event = VALID_EVENT_BY_OPERATION[operation]
            flaw = ""

        plan.append(
            PlannedRequest(
                index=index,
                run_id=run_id,
                request_id=f"sim-{run_id}-{index:06d}",
                scheduled_min=minute,
                operation=operation,
                intended_event=event,
                intent=INTENT_INVALID if invalid else INTENT_VALID,
                expected_status=EVENT_EXPECTED_STATUS[event],
                category=category,
                customer_tier=CUSTOMER_TIERS[int(tiers[index])],
                amount=float(amounts[index]),
                payload_flaw=flaw,
                scenario=scenario.effect if scenario else "",
            )
        )
    return tuple(plan)


# --- Resolving a planned request into an HTTP call -------------------------

FALLBACK_POOL_EMPTY = "pool_empty"

MISSING_ORDER_STATUS = 404


class OrderPool:
    """The orders the API confirmed during this run.

    Which identifier a read or a cancel touches cannot be planned in advance,
    because it only exists once a create has been answered. The pool keeps
    three views of that live state:

    * every known order, for reads;
    * the orders still open, so two cancels never fight over one order;
    * the orders already cancelled, to build an impossible sequence on purpose.
    """

    def __init__(self) -> None:
        self._known: list[str] = []
        self._open: dict[str, None] = {}
        self._cancelled: list[str] = []

    def add_created(self, order_id: str) -> None:
        self._known.append(order_id)
        self._open[order_id] = None

    def add_cancelled(self, order_id: str) -> None:
        self._open.pop(order_id, None)
        self._cancelled.append(order_id)

    def pick_known(self, index: int) -> str | None:
        """Any confirmed order, rotating so the load spreads over the pool."""
        if not self._known:
            return None
        return self._known[index % len(self._known)]

    def take_open(self) -> str | None:
        """Claim an order nobody else will cancel."""
        if not self._open:
            return None
        order_id = next(iter(self._open))
        del self._open[order_id]
        return order_id

    def pick_cancelled(self, index: int) -> str | None:
        if not self._cancelled:
            return None
        return self._cancelled[index % len(self._cancelled)]


@dataclass(frozen=True)
class HttpCall:
    """The concrete request to put on the wire."""

    method: str
    path: str
    json_body: Any
    order_id: str
    expected_status: int
    fallback: str


def _missing_order_id(index: int) -> str:
    """An identifier the API cannot know, for the deliberate ``404``."""
    return f"ord_missing_{index:06d}"


def build_call(planned: PlannedRequest, pool: OrderPool) -> HttpCall:
    """Bind a planned request to a real path, using the live order pool.

    When the pool cannot satisfy the intent — a read planned before any create
    has been answered — the call degrades to an unknown identifier and says so
    in ``fallback``, so the resulting ``404`` is not mistaken for a defect.
    """
    event = planned.intended_event

    if planned.operation == OPERATION_CREATE:
        return HttpCall(
            method="POST",
            path="/orders",
            json_body=order_payload(planned),
            order_id="",
            expected_status=planned.expected_status,
            fallback="",
        )

    if event == EVENT_READ_VALID:
        order_id = pool.pick_known(planned.index)
    elif event == EVENT_CANCEL_VALID:
        order_id = pool.take_open()
    elif event == EVENT_CANCEL_ALREADY_CANCELLED:
        order_id = pool.pick_cancelled(planned.index)
    else:  # the deliberate unknown identifier
        order_id = _missing_order_id(planned.index)

    fallback = ""
    expected_status = planned.expected_status
    if order_id is None:
        order_id = _missing_order_id(planned.index)
        fallback = FALLBACK_POOL_EMPTY
        expected_status = MISSING_ORDER_STATUS

    if planned.operation == OPERATION_CANCEL:
        return HttpCall(
            method="POST",
            path=f"/orders/{order_id}/cancel",
            json_body=None,
            order_id=order_id,
            expected_status=expected_status,
            fallback=fallback,
        )
    return HttpCall(
        method="GET",
        path=f"/orders/{order_id}",
        json_body=None,
        order_id=order_id,
        expected_status=expected_status,
        fallback=fallback,
    )


# --- Results ---------------------------------------------------------------

RESULT_AS_EXPECTED = "as_expected"
RESULT_UNEXPECTED = "unexpected"
RESULT_SERVER_ERROR = "server_error"
RESULT_TRANSPORT_ERROR = "transport_error"


def classify_result(expected_status: int, status_code: int | None) -> str:
    """Compare the intent with the answer.

    A ``5xx`` is always a server failure, even when the request was broken on
    purpose: the simulator never asks for one, so those rows must stay
    separable from the intentional client errors.
    """
    if status_code is None:
        return RESULT_TRANSPORT_ERROR
    if status_code >= 500:
        return RESULT_SERVER_ERROR
    if status_code == expected_status:
        return RESULT_AS_EXPECTED
    return RESULT_UNEXPECTED


@dataclass(frozen=True)
class RequestRecord:
    """One CSV row: what was intended next to what actually happened."""

    request_id: str
    scheduled_at: datetime
    sent_at: datetime
    operation: str
    intended_event: str
    status_code: int | None
    client_latency_ms: float
    intent: str
    expected_status: int
    result: str
    order_id: str
    category: str
    customer_tier: str
    amount: float
    scheduled_min: float
    scenario: str
    payload_flaw: str
    fallback: str
    error: str
    response_request_id: str

    def as_row(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "scheduled_at": self.scheduled_at.isoformat(),
            "sent_at": self.sent_at.isoformat(),
            "operation": self.operation,
            "intended_event": self.intended_event,
            "status_code": "" if self.status_code is None else self.status_code,
            "client_latency_ms": round(self.client_latency_ms, 3),
            "intent": self.intent,
            "expected_status": self.expected_status,
            "result": self.result,
            "order_id": self.order_id,
            "category": self.category,
            "customer_tier": self.customer_tier,
            "amount": self.amount,
            "scheduled_min": round(self.scheduled_min, 6),
            "scenario": self.scenario,
            "payload_flaw": self.payload_flaw,
            "fallback": self.fallback,
            "error": self.error,
            "response_request_id": self.response_request_id,
        }


CSV_FIELDS = (
    "request_id",
    "scheduled_at",
    "sent_at",
    "operation",
    "intended_event",
    "status_code",
    "client_latency_ms",
    "intent",
    "expected_status",
    "result",
    "order_id",
    "category",
    "customer_tier",
    "amount",
    "scheduled_min",
    "scenario",
    "payload_flaw",
    "fallback",
    "error",
    "response_request_id",
)


class CsvRecorder:
    """Append one row per request, flushing as the run goes.

    Rows are written in completion order and flushed immediately, so a run cut
    short keeps everything it had already measured. ``scheduled_at`` and
    ``scheduled_min`` restore the chronological order during analysis.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._handle = None
        self._writer = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=list(CSV_FIELDS))
        self._writer.writeheader()
        self._handle.flush()
        return self

    def write(self, record: RequestRecord) -> None:
        if self._writer is None or self._handle is None:  # pragma: no cover
            raise RuntimeError("CsvRecorder must be used as a context manager")
        self._writer.writerow(record.as_row())
        self._handle.flush()

    def __exit__(self, *exc_info: object) -> None:
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._writer = None


# --- Execution -------------------------------------------------------------


def connection_limits(config: SimulatorConfig) -> httpx.Limits:
    """Cap the pool so ``n_requests`` never becomes ``n_requests`` sockets."""
    return httpx.Limits(
        max_connections=config.max_connections,
        max_keepalive_connections=config.max_connections,
    )


def request_timeout(config: SimulatorConfig) -> httpx.Timeout:
    return httpx.Timeout(config.timeout_s)


AUTH_HEADER = "Authorization"
AUTH_SCHEME = "Bearer"
AUTH_TOKEN_VAR = "CLOUDPULSE_AUTH_TOKEN"


def auth_headers(token: str) -> dict[str, str]:
    """The authorisation header for a private function, or nothing.

    A deployed Cloud Run function that grants no access to `allUsers` answers
    403 unless the caller proves who it is, so the laboratory run needs an
    identity token — minted outside this process, for example with
    ``gcloud auth print-identity-token``.

    The value is stripped (the token printed by ``gcloud`` ends in a newline)
    and an already-prefixed value is not prefixed twice.
    """
    token = (token or "").strip()
    if not token:
        return {}
    if token.startswith(f"{AUTH_SCHEME} "):
        return {AUTH_HEADER: token}
    return {AUTH_HEADER: f"{AUTH_SCHEME} {token}"}


class TokenError(RuntimeError):
    """A token could not be minted. Never carries the token itself."""


@dataclass(frozen=True)
class IdentityTokenSource:
    """Mints identity tokens by running a command, keeping them in memory only.

    The default command is the one the laboratory uses:
    ``gcloud auth print-identity-token --quiet``. Two properties matter:

    * the credential comes back on stdout and is NEVER an argument, so it
      cannot be read from the process list by another user on the machine;
    * nothing is written to disk — no token file, no environment export.

    The command is a tuple, run without a shell, so no value can be
    reinterpreted as shell syntax.
    """

    command: tuple[str, ...] = (
        "gcloud",
        "auth",
        "print-identity-token",
        "--quiet",
    )

    async def fetch(self) -> str:
        """Run the command and return the token it printed.

        Raises ``TokenError`` on any failure, with the exit status and the
        first line of stderr for diagnosis — the token lives on stdout, which
        is never included in the message.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise TokenError(f"cannot run {self.command[0]}: {error}") from error

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", "replace").strip().splitlines()
            raise TokenError(
                f"{self.command[0]} exited with {process.returncode}"
                + (f": {detail[0][:200]}" if detail else "")
            )

        token = stdout.decode("utf-8", "replace").strip()
        if not token:
            raise TokenError(f"{self.command[0]} printed an empty token")
        return token


def apply_auth(client: httpx.AsyncClient, token: str) -> None:
    """Swap the credential a live client sends, or remove it.

    Requests already in flight keep the header they were built with, which is
    harmless: the previous token is still valid for the rest of its life.
    """
    headers = auth_headers(token)
    if headers:
        client.headers[AUTH_HEADER] = headers[AUTH_HEADER]
    else:
        client.headers.pop(AUTH_HEADER, None)


async def renew_auth_periodically(
    client: httpx.AsyncClient,
    fetch: Callable[[], Awaitable[str]],
    interval_s: float,
    *,
    on_error: Callable[[TokenError], None] | None = None,
) -> None:
    """Replace the client's token every ``interval_s`` until cancelled.

    The first renewal happens after one interval, so the token handed in at
    startup is used for its first half-life instead of being thrown away.

    A failed renewal is reported and the loop continues with the token already
    in place: a transient `gcloud` hiccup must not abort a run that cannot be
    repeated cheaply. The run only breaks if every attempt keeps failing until
    the current token actually expires.
    """
    while True:
        await asyncio.sleep(interval_s)
        try:
            apply_auth(client, await fetch())
        except TokenError as error:
            if on_error is not None:
                on_error(error)


def build_client(config: SimulatorConfig, auth_token: str = "") -> httpx.AsyncClient:
    """One client for the whole run.

    The token travels as a default header of the client, so every request
    carries it without `_execute` ever handling the credential — which is also
    what keeps it out of the CSV rows and of every summary.
    """
    return httpx.AsyncClient(
        base_url=config.target_url,
        limits=connection_limits(config),
        timeout=request_timeout(config),
        headers=auth_headers(auth_token),
    )


def _learn_from_response(
    pool: OrderPool,
    planned: PlannedRequest,
    call: HttpCall,
    response: httpx.Response,
) -> str:
    """Feed the pool with what the API confirmed, and name the order touched.

    A create only learns its identifier here, which is also the value the CSV
    needs so the row can be joined with the API log event of the same order.
    """
    if planned.operation == OPERATION_CREATE and response.status_code == 201:
        try:
            order_id = response.json().get("id")
        except ValueError:
            return ""
        if isinstance(order_id, str) and order_id:
            pool.add_created(order_id)
            return order_id
        return ""
    if (
        planned.intended_event == EVENT_CANCEL_VALID
        and response.status_code == 200
        and call.order_id
    ):
        pool.add_cancelled(call.order_id)
    return call.order_id


async def _execute(
    client: httpx.AsyncClient,
    planned: PlannedRequest,
    pool: OrderPool,
    scheduled_at: datetime,
    on_record: Callable[[RequestRecord], None] | None,
) -> RequestRecord:
    """Send one request and record it, whatever happens to it."""
    call = build_call(planned, pool)
    sent_at = datetime.now(UTC)
    started = time.perf_counter()

    status_code: int | None = None
    error = ""
    response_request_id = ""
    order_id = call.order_id
    try:
        response = await client.request(
            call.method,
            call.path,
            json=call.json_body,
            headers={REQUEST_ID_HEADER: planned.request_id},
        )
        status_code = response.status_code
        response_request_id = response.headers.get(REQUEST_ID_HEADER, "")
        order_id = _learn_from_response(pool, planned, call, response)
    except Exception as failure:  # noqa: BLE001 - a lost row is a lost datapoint
        error = type(failure).__name__

    record = RequestRecord(
        request_id=planned.request_id,
        scheduled_at=scheduled_at,
        sent_at=sent_at,
        operation=planned.operation,
        intended_event=planned.intended_event,
        status_code=status_code,
        client_latency_ms=(time.perf_counter() - started) * 1000,
        intent=planned.intent,
        expected_status=call.expected_status,
        result=classify_result(call.expected_status, status_code),
        order_id=order_id,
        category=planned.category,
        customer_tier=planned.customer_tier,
        amount=planned.amount,
        scheduled_min=planned.scheduled_min,
        scenario=planned.scenario,
        payload_flaw=planned.payload_flaw,
        fallback=call.fallback,
        error=error,
        response_request_id=response_request_id,
    )
    if on_record is not None:
        on_record(record)
    return record


def _lost_record(
    planned: PlannedRequest, scheduled_at: datetime, failure: BaseException
) -> RequestRecord:
    """A row for a request whose own task died — the CSV loses nothing."""
    moment = datetime.now(UTC)
    return RequestRecord(
        request_id=planned.request_id,
        scheduled_at=scheduled_at,
        sent_at=moment,
        operation=planned.operation,
        intended_event=planned.intended_event,
        status_code=None,
        client_latency_ms=0.0,
        intent=planned.intent,
        expected_status=planned.expected_status,
        result=RESULT_TRANSPORT_ERROR,
        order_id="",
        category=planned.category,
        customer_tier=planned.customer_tier,
        amount=planned.amount,
        scheduled_min=planned.scheduled_min,
        scenario=planned.scenario,
        payload_flaw=planned.payload_flaw,
        fallback="",
        error=type(failure).__name__,
        response_request_id="",
    )


async def dispatch(
    client: httpx.AsyncClient,
    config: SimulatorConfig,
    plan: Sequence[PlannedRequest],
    on_record: Callable[[RequestRecord], None] | None = None,
) -> list[RequestRecord]:
    """Fire every request at its instant, never waiting for the previous one.

    The loop only ever sleeps until the next due instant; the request itself
    runs in its own task, so a slow or hanging response cannot push the rest of
    the schedule back. Concurrency is bounded by the client's connection pool,
    not by the dispatcher.
    """
    pool = OrderPool()
    started_wall = datetime.now(UTC)
    started_at = time.monotonic()

    tasks: list[asyncio.Task[RequestRecord]] = []
    scheduled_moments: list[datetime] = []
    for planned in plan:
        due = planned.due_seconds(config.seconds_per_minute)
        delay = due - (time.monotonic() - started_at)
        if delay > 0:
            await asyncio.sleep(delay)
        scheduled_at = started_wall + timedelta(seconds=due)
        scheduled_moments.append(scheduled_at)
        tasks.append(
            asyncio.create_task(
                _execute(client, planned, pool, scheduled_at, on_record)
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    records: list[RequestRecord] = []
    for planned, scheduled_at, result in zip(
        plan, scheduled_moments, results, strict=True
    ):
        if isinstance(result, BaseException):
            record = _lost_record(planned, scheduled_at, result)
            if on_record is not None:
                on_record(record)
            records.append(record)
        else:
            records.append(result)
    return records


async def run_simulation(
    config: SimulatorConfig,
    plan: Sequence[PlannedRequest],
    on_record: Callable[[RequestRecord], None] | None = None,
    auth_token: str = "",
    token_source: IdentityTokenSource | None = None,
) -> list[RequestRecord]:
    """Open one client for the whole run and dispatch the plan over it.

    With a ``token_source`` the credential lifecycle belongs here: one token is
    minted before the first request and replaced every ``token_refresh_s``
    until the run ends. The renewal task is always cancelled, so no background
    task outlives the run.
    """
    failures: list[TokenError] = []
    if token_source is not None and not auth_token:
        auth_token = await token_source.fetch()

    async with build_client(config, auth_token) as client:
        renewal: asyncio.Task[None] | None = None
        if token_source is not None:
            renewal = asyncio.create_task(
                renew_auth_periodically(
                    client,
                    token_source.fetch,
                    config.token_refresh_s,
                    on_error=failures.append,
                )
            )
        try:
            records = await dispatch(client, config, plan, on_record)
        finally:
            if renewal is not None:
                renewal.cancel()
                with suppress(asyncio.CancelledError):
                    await renewal

    for failure in failures:
        print(f"warning: token renewal failed: {failure}", file=sys.stderr)
    return records


# --- Summary ---------------------------------------------------------------


def _percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile; no interpolation, no numpy round trip."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[position]


def summarise(records: Sequence[RequestRecord]) -> dict[str, Any]:
    """Counts worth printing at the end of a run."""
    latencies = [
        record.client_latency_ms for record in records if record.status_code is not None
    ]
    return {
        "requests": len(records),
        "by_result": Counter(record.result for record in records),
        "by_status": Counter(
            record.status_code for record in records if record.status_code is not None
        ),
        "by_event": Counter(record.intended_event for record in records),
        "intentional_errors": sum(
            record.intent == INTENT_INVALID for record in records
        ),
        "server_errors": sum(
            record.result == RESULT_SERVER_ERROR for record in records
        ),
        "transport_errors": sum(
            record.result == RESULT_TRANSPORT_ERROR for record in records
        ),
        "pool_fallbacks": sum(bool(record.fallback) for record in records),
        "latency_p50_ms": round(_percentile(latencies, 0.50), 3),
        "latency_p95_ms": round(_percentile(latencies, 0.95), 3),
    }


# --- Command line ----------------------------------------------------------

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line.

    Every flag maps to one configuration field, so a run can be shrunk for a
    rehearsal without editing — or risking — the laboratory configuration.
    """
    parser = argparse.ArgumentParser(
        prog="simulator",
        description="Generate the CloudPulse HTTP traffic experiment.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="configuration file (default: %(default)s)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="run the small, seconds-long rehearsal declared under 'quick'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and describe the plan without sending a single request",
    )
    parser.add_argument("--target-url", help="base URL of the orders API")
    parser.add_argument("--n-requests", type=int, help="number of requests to send")
    parser.add_argument("--duration-min", type=float, help="length of the window")
    parser.add_argument(
        "--seconds-per-minute",
        type=float,
        help="wall-clock seconds per simulated minute (60 keeps real time)",
    )
    parser.add_argument("--seed", type=int, help="seed of the random generator")
    parser.add_argument("--timeout", type=float, help="per-request timeout in seconds")
    parser.add_argument(
        "--max-connections", type=int, help="cap on simultaneous connections"
    )
    parser.add_argument("--output", type=Path, help="where to write requests.csv")
    parser.add_argument(
        "--run-id",
        help="identifier embedded in every X-Request-ID (default: random)",
    )
    parser.add_argument(
        "--renew-token",
        action="store_true",
        help=(
            "mint an identity token with `gcloud auth print-identity-token` and "
            "renew it every token_refresh_s. Required for the 60-minute run: a "
            "token lives about an hour, so a single one expires mid-run."
        ),
    )
    parser.add_argument(
        "--auth-token",
        help=(
            "identity token for a private function, sent as "
            "'Authorization: Bearer <token>'. Prefer the "
            f"{AUTH_TOKEN_VAR} environment variable: a token on the command "
            "line is visible in the shell history and in the process list."
        ),
    )
    return parser.parse_args(argv)


def resolve_token_source(args: argparse.Namespace) -> IdentityTokenSource | None:
    """The source that keeps the run authenticated, or ``None`` for a fixed token."""
    return IdentityTokenSource() if getattr(args, "renew_token", False) else None


def resolve_auth_token(args: argparse.Namespace, environ: Mapping[str, str]) -> str:
    """The token to authenticate with: the flag, then the environment, then none.

    Kept out of `SimulatorConfig` on purpose: that object is printed by
    `describe_plan` and a credential must not be able to travel that way.
    """
    return (
        getattr(args, "auth_token", None) or environ.get(AUTH_TOKEN_VAR, "")
    ).strip()


_OVERRIDE_BY_FLAG = {
    "target_url": "target_url",
    "n_requests": "n_requests",
    "duration_min": "duration_min",
    "seconds_per_minute": "seconds_per_minute",
    "seed": "seed",
    "timeout": "timeout_s",
    "max_connections": "max_connections",
    "output": "output_csv",
}


def configure(args: argparse.Namespace) -> SimulatorConfig:
    """Resolve the configuration: file, then quick preset, then explicit flags."""
    config = load_config(args.config)
    if args.quick:
        config = config.for_quick_run()
    overrides = {
        field: getattr(args, flag)
        for flag, field in _OVERRIDE_BY_FLAG.items()
        if getattr(args, flag, None) is not None
    }
    return config.with_overrides(**overrides) if overrides else config


def describe_plan(config: SimulatorConfig, plan: Sequence[PlannedRequest]) -> str:
    """A human-readable account of the traffic a plan would produce."""
    operations = Counter(request.operation for request in plan)
    events = Counter(request.intended_event for request in plan)
    intentional = sum(request.intent == INTENT_INVALID for request in plan)
    scenario_hits = Counter(request.scenario for request in plan if request.scenario)

    lines = [
        f"target            {config.target_url}",
        f"requests          {len(plan)}",
        (
            f"window            0 - {config.duration_min:g} min"
            f" in {config.duration_seconds:g} s of wall clock"
        ),
        (
            f"arrivals          N(mu={config.mu_min:g}, sigma={config.sigma_min:g})"
            f" clipped to the window, seed {config.seed}"
        ),
        (
            f"first / last      {plan[0].scheduled_min:.2f} /"
            f" {plan[-1].scheduled_min:.2f} min"
        ),
        "operations        "
        + ", ".join(f"{name} {operations[name]}" for name in OPERATIONS),
        (
            f"intentional errors {intentional}"
            f" ({intentional / len(plan):.1%}, configured {config.invalid_share:.1%})"
        ),
        "events            "
        + ", ".join(f"{name} {count}" for name, count in sorted(events.items())),
        "scenarios         "
        + (
            ", ".join(
                f"{scenario.effect} [{scenario.start_min:g}, {scenario.end_min:g}) min"
                f" on {scenario.category}: {scenario_hits[scenario.effect]} requests"
                for scenario in config.scenarios
            )
            or "none"
        ),
        (
            f"connections       at most {config.max_connections},"
            f" timeout {config.timeout_s:g} s"
        ),
        f"output            {config.output_csv}",
    ]
    return "\n".join(lines)


def describe_run(summary: dict[str, Any]) -> str:
    """A human-readable account of what a finished run actually produced."""
    return "\n".join(
        [
            f"requests sent      {summary['requests']}",
            "by result          "
            + ", ".join(
                f"{name} {count}"
                for name, count in sorted(summary["by_result"].items())
            ),
            "by status          "
            + (
                ", ".join(
                    f"{status} {count}"
                    for status, count in sorted(summary["by_status"].items())
                )
                or "none"
            ),
            f"intentional errors {summary['intentional_errors']}",
            f"server errors      {summary['server_errors']}",
            f"transport errors   {summary['transport_errors']}",
            f"pool fallbacks     {summary['pool_fallbacks']}",
            (
                f"client latency     p50 {summary['latency_p50_ms']:g} ms,"
                f" p95 {summary['latency_p95_ms']:g} ms"
            ),
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: resolve, plan, and — unless asked not to — send."""
    args = parse_args(argv)
    try:
        config = configure(args)
    except ConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    auth_token = resolve_auth_token(args, os.environ)
    token_source = resolve_token_source(args)
    run_id = args.run_id or uuid.uuid4().hex[:8]
    plan = build_plan(config, run_id=run_id)

    print(f"run id            {run_id}")
    print(describe_plan(config, plan))
    if token_source is not None:
        print(
            "authentication    bearer identity token, renewed every "
            f"{config.token_refresh_s:g} s (values never shown)"
        )
    else:
        print(
            "authentication    "
            + ("bearer identity token (value not shown)" if auth_token else "none")
        )

    if args.dry_run:
        print("\ndry run: no request was sent")
        return 0

    print(f"\nsending {len(plan)} requests over {config.duration_seconds:g} s ...")
    with CsvRecorder(config.output_csv) as recorder:
        records = asyncio.run(
            run_simulation(config, plan, recorder.write, auth_token, token_source)
        )

    print()
    print(describe_run(summarise(records)))
    print(f"\nrows written      {len(records)} -> {config.output_csv}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
