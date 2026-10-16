"""The simulator against the real phase 1 function, over real sockets.

Everything here runs the orders API from ``backend/main.py`` inside a local
HTTP server, so a mismatch between what the simulator sends and what the API
accepts shows up as a failing test instead of as a wall of unexplained ``400``
rows during the 60 minute run.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import threading

import pytest
from conftest import BACKEND_MAIN, planned_request
from functions_framework import create_app
from werkzeug.serving import make_server

from simulator.simulator import (
    EVENT_CANCEL_ALREADY_CANCELLED,
    EVENT_CANCEL_MISSING,
    EVENT_CANCEL_VALID,
    EVENT_CREATE_INVALID_PAYLOAD,
    EVENT_CREATE_VALID,
    EVENT_READ_MISSING,
    EVENT_READ_VALID,
    PAYLOAD_FLAWS,
    RESULT_AS_EXPECTED,
    RESULT_SERVER_ERROR,
    build_client,
    build_plan,
    dispatch,
    load_config,
    main,
    summarise,
)


@pytest.fixture(scope="module")
def live_api():
    """The phase 1 function served over HTTP on a loopback port."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = create_app(target="handle", source=str(BACKEND_MAIN))
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def config(lab_config_path, live_api, tmp_path):
    """The laboratory configuration pointed at the local server."""
    return load_config(lab_config_path).with_overrides(
        target_url=live_api,
        n_requests=40,
        seconds_per_minute=0.01,
        output_csv=tmp_path / "requests.csv",
    )


def run(config, plan, on_record=None):
    async def runner():
        async with build_client(config) as client:
            return await dispatch(client, config, plan, on_record)

    return asyncio.run(runner())


# --- Every intended event against the real contract -----------------------


def test_each_intended_event_earns_the_status_the_plan_expects(config):
    """One request per event, in an order that lets each intent be satisfiable.

    The clock is slowed to 0.5 s per simulated minute on purpose: a read can
    only reuse an order once the create has been *answered*, and at the
    compression used by the other tests the responses arrive after the read is
    already due. The real run leaves ~0.6 s between requests, so the pool is
    never this cold.
    """
    unhurried = config.with_overrides(seconds_per_minute=0.5)
    plan = (
        planned_request(index=0, event=EVENT_CREATE_VALID, minute=0.0),
        planned_request(index=1, event=EVENT_CREATE_VALID, minute=0.1),
        planned_request(index=2, event=EVENT_CREATE_VALID, minute=0.2),
        planned_request(index=3, event=EVENT_READ_VALID, minute=0.3),
        planned_request(index=4, event=EVENT_CANCEL_VALID, minute=0.4),
        planned_request(index=5, event=EVENT_CANCEL_ALREADY_CANCELLED, minute=0.5),
        planned_request(index=6, event=EVENT_READ_MISSING, minute=0.6),
        planned_request(index=7, event=EVENT_CANCEL_MISSING, minute=0.7),
        planned_request(
            index=8,
            event=EVENT_CREATE_INVALID_PAYLOAD,
            minute=0.8,
            flaw="missing_amount",
        ),
    )

    records = run(unhurried, plan)

    for record, request in zip(records, plan, strict=True):
        assert record.fallback == "", f"{request.intended_event} had no order to use"
        assert record.result == RESULT_AS_EXPECTED, (
            f"{request.intended_event}: expected {record.expected_status},"
            f" got {record.status_code}"
        )


@pytest.mark.parametrize("flaw", PAYLOAD_FLAWS)
def test_every_broken_payload_is_rejected_by_the_real_api(config, flaw):
    plan = (planned_request(index=0, event=EVENT_CREATE_INVALID_PAYLOAD, flaw=flaw),)

    record = run(config, plan)[0]

    assert record.status_code == 400, f"{flaw} was not rejected"
    assert record.result == RESULT_AS_EXPECTED


def test_a_valid_create_is_accepted_with_the_identifier_the_api_minted(config):
    record = run(config, (planned_request(event=EVENT_CREATE_VALID),))[0]

    assert record.status_code == 201
    assert record.order_id.startswith("ord_")


def test_the_api_echoes_the_correlation_identifier_of_every_request(config):
    plan = build_plan(config, run_id="echo")

    records = run(config, plan)

    for record in records:
        assert record.response_request_id == record.request_id


def test_a_simulated_backend_failure_is_recorded_as_a_server_error(config, monkeypatch):
    """``FAILURE_RATE=1`` turns every answer into a ``500``, intent aside."""
    monkeypatch.setenv("FAILURE_RATE", "1")
    plan = (
        planned_request(index=0, event=EVENT_CREATE_VALID),
        planned_request(
            index=1, event=EVENT_CREATE_INVALID_PAYLOAD, flaw="bad_category"
        ),
    )

    records = run(config, plan)

    assert [record.result for record in records] == [RESULT_SERVER_ERROR] * 2
    assert all(record.status_code == 500 for record in records)


# --- A whole small run -----------------------------------------------------


def test_a_small_run_against_the_real_api_produces_no_unexplained_failures(config):
    plan = build_plan(config, run_id="small")

    records = run(config, plan)
    summary = summarise(records)

    assert summary["requests"] == len(plan)
    assert summary["transport_errors"] == 0
    assert summary["server_errors"] == 0
    unexplained = [
        record
        for record in records
        if record.result != RESULT_AS_EXPECTED and not record.fallback
    ]
    assert not unexplained, [
        (r.intended_event, r.expected_status, r.status_code) for r in unexplained
    ]


def test_the_run_can_be_traced_from_the_csv_to_the_api_log_events(
    config, capsys, lab_config_path
):
    """Each CSV row must be joinable with the event the API logged for it."""
    exit_code = main(
        [
            "--config",
            str(lab_config_path),
            "--quick",
            "--target-url",
            config.target_url,
            "--output",
            str(config.output_csv),
            "--run-id",
            "trace",
        ]
    )
    captured = capsys.readouterr().out

    assert exit_code == 0

    rows = list(csv.DictReader(config.output_csv.read_text().splitlines()))
    assert len(rows) == 30

    events = {
        json.loads(line)["request_id"]: json.loads(line)
        for line in captured.splitlines()
        if line.startswith('{"severity"')
    }
    for row in rows:
        event = events.get(row["request_id"])
        assert event is not None, f"no API log event for {row['request_id']}"
        assert str(event["status_code"]) == row["status_code"]


def test_the_quick_run_writes_the_csv_where_it_was_asked_to(config, lab_config_path):
    target = config.output_csv.parent / "elsewhere.csv"

    main(
        [
            "--config",
            str(lab_config_path),
            "--quick",
            "--target-url",
            config.target_url,
            "--output",
            str(target),
        ]
    )

    assert target.exists()
    assert len(target.read_text().splitlines()) == 31
