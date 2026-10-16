"""Shared fixtures for the CloudPulse tests.

The backend tests drive the real Functions Framework application loaded from
``backend/main.py``, so routing, payload parsing, error mapping and the
structured log event are all exercised over real HTTP requests instead of by
calling internal helpers.

The simulator tests import ``simulator.simulator`` from the repository root,
which is why that root is placed on ``sys.path`` here instead of relying on the
way pytest happens to be invoked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from functions_framework import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_MAIN = REPO_ROOT / "backend" / "main.py"
LAB_CONFIG = REPO_ROOT / "simulator" / "config.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from simulator import simulator


@pytest.fixture
def app():
    """Load a fresh app so every test starts with an empty in-memory store."""
    return create_app(target="handle", source=str(BACKEND_MAIN))


@pytest.fixture
def api(app):
    """HTTP test client for the loaded function."""
    return app.test_client()


@pytest.fixture
def read_events(capsys):
    """Return a reader for the JSON log events emitted to stdout so far."""

    def _read():
        stdout = capsys.readouterr().out
        return [
            json.loads(line) for line in stdout.splitlines() if line.startswith("{")
        ]

    return _read


@pytest.fixture
def valid_order():
    """Minimal payload accepted by ``POST /orders``."""
    return {"customer_tier": "premium", "category": "electronics", "amount": 149.99}


@pytest.fixture(autouse=True)
def clean_runtime_env(monkeypatch):
    """Keep the runtime knobs unset unless a test sets them explicitly."""
    monkeypatch.delenv("FAILURE_RATE", raising=False)
    monkeypatch.delenv("EXTRA_LATENCY_MS", raising=False)


@pytest.fixture
def backend_module(app):
    """The module instance the loaded app calls into, for fault injection.

    Functions Framework registers the loaded source under its file stem, so
    ``sys.modules["main"]`` is the very module object backing ``app``.
    """
    return sys.modules["main"]


@pytest.fixture(scope="session")
def lab_config_path():
    """Path to the configuration file shipped with the laboratory."""
    return LAB_CONFIG


_OPERATION_BY_EVENT = {
    simulator.EVENT_CREATE_VALID: simulator.OPERATION_CREATE,
    simulator.EVENT_CREATE_INVALID_PAYLOAD: simulator.OPERATION_CREATE,
    simulator.EVENT_READ_VALID: simulator.OPERATION_READ,
    simulator.EVENT_READ_MISSING: simulator.OPERATION_READ,
    simulator.EVENT_CANCEL_VALID: simulator.OPERATION_CANCEL,
    simulator.EVENT_CANCEL_MISSING: simulator.OPERATION_CANCEL,
    simulator.EVENT_CANCEL_ALREADY_CANCELLED: simulator.OPERATION_CANCEL,
}

_VALID_EVENTS = frozenset(
    {
        simulator.EVENT_CREATE_VALID,
        simulator.EVENT_READ_VALID,
        simulator.EVENT_CANCEL_VALID,
    }
)


def planned_request(
    index=0,
    event=simulator.EVENT_CREATE_VALID,
    minute=0.0,
    flaw="",
    category="electronics",
    customer_tier="premium",
    amount=149.99,
):
    """One planned request, built without going through the plan generator.

    The simulator tests need requests with a chosen intent, which the seeded
    generator cannot be asked for.
    """
    return simulator.PlannedRequest(
        index=index,
        run_id="test",
        request_id=f"sim-test-{index:06d}",
        scheduled_min=minute,
        operation=_OPERATION_BY_EVENT[event],
        intended_event=event,
        intent=(
            simulator.INTENT_VALID
            if event in _VALID_EVENTS
            else simulator.INTENT_INVALID
        ),
        expected_status=simulator.EVENT_EXPECTED_STATUS[event],
        category=category,
        customer_tier=customer_tier,
        amount=amount,
        payload_flaw=flaw,
        scenario="",
    )
