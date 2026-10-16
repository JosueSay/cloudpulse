"""Executing a plan: real HTTP calls, concurrency, CSV rows and failures.

The API is replaced by an ``httpx.MockTransport`` here so the tests can force
slow responses, timeouts and connection failures on demand. The real phase 1
function is exercised over a local HTTP server in
``test_simulator_api_contract.py``.
"""

from __future__ import annotations

import asyncio
import csv
import itertools
import time
from datetime import UTC, datetime

import httpx
import pytest
from conftest import planned_request as planned

from simulator.simulator import (
    CSV_FIELDS,
    EVENT_CANCEL_ALREADY_CANCELLED,
    EVENT_CANCEL_MISSING,
    EVENT_CANCEL_VALID,
    EVENT_CREATE_INVALID_PAYLOAD,
    EVENT_CREATE_VALID,
    EVENT_READ_MISSING,
    EVENT_READ_VALID,
    FALLBACK_POOL_EMPTY,
    INTENT_INVALID,
    INTENT_VALID,
    OPERATION_CREATE,
    REQUEST_ID_HEADER,
    RESULT_AS_EXPECTED,
    RESULT_SERVER_ERROR,
    RESULT_TRANSPORT_ERROR,
    RESULT_UNEXPECTED,
    CsvRecorder,
    OrderPool,
    build_call,
    build_client,
    build_plan,
    connection_limits,
    dispatch,
    load_config,
    request_timeout,
    summarise,
)


@pytest.fixture
def config(lab_config_path):
    """A configuration whose whole run fits in a fraction of a second."""
    return load_config(lab_config_path).with_overrides(
        n_requests=20, seconds_per_minute=0.002
    )


def fake_orders_api(latency_s=0.0, status_for=None):
    """A minimal stand-in for the orders API, with an inspectable journal."""
    ids = itertools.count(1)
    journal = []

    async def handler(request):
        journal.append(request)
        if latency_s:
            await asyncio.sleep(latency_s)
        if status_for is not None:
            forced = status_for(request)
            if forced is not None:
                return httpx.Response(forced, json={"error": "forced"})
        if request.method == "POST" and request.url.path == "/orders":
            return httpx.Response(201, json={"id": f"ord_{next(ids):08d}"})
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"status": "cancelled"})
        return httpx.Response(200, json={"status": "created"})

    handler.journal = journal
    return handler


def run_dispatch(config, plan, handler, on_record=None):
    async def runner():
        async with httpx.AsyncClient(
            base_url=config.target_url, transport=httpx.MockTransport(handler)
        ) as client:
            return await dispatch(client, config, plan, on_record=on_record)

    return asyncio.run(runner())


# --- Turning a planned request into an HTTP call ---------------------------


def test_a_create_is_posted_to_the_orders_collection():
    call = build_call(planned(event=EVENT_CREATE_VALID), OrderPool())

    assert call.method == "POST"
    assert call.path == "/orders"
    assert call.json_body == {
        "customer_tier": "premium",
        "category": "electronics",
        "amount": 149.99,
    }


def test_a_broken_create_is_sent_to_the_same_endpoint_with_a_broken_body():
    call = build_call(
        planned(event=EVENT_CREATE_INVALID_PAYLOAD, flaw="missing_amount"), OrderPool()
    )

    assert (call.method, call.path) == ("POST", "/orders")
    assert "amount" not in call.json_body
    assert call.expected_status == 400


def test_a_valid_read_targets_an_order_the_run_created():
    pool = OrderPool()
    pool.add_created("ord_1")

    call = build_call(planned(event=EVENT_READ_VALID), pool)

    assert call.method == "GET"
    assert call.path == "/orders/ord_1"
    assert call.json_body is None
    assert call.expected_status == 200
    assert call.fallback == ""


def test_a_valid_cancel_targets_an_order_that_is_still_open():
    pool = OrderPool()
    pool.add_created("ord_1")

    call = build_call(planned(event=EVENT_CANCEL_VALID), pool)

    assert call.method == "POST"
    assert call.path == "/orders/ord_1/cancel"
    assert call.expected_status == 200


def test_two_valid_cancels_never_compete_for_the_same_order():
    pool = OrderPool()
    pool.add_created("ord_1")
    pool.add_created("ord_2")

    first = build_call(planned(index=1, event=EVENT_CANCEL_VALID), pool)
    second = build_call(planned(index=2, event=EVENT_CANCEL_VALID), pool)

    assert first.order_id != second.order_id


def test_an_impossible_sequence_cancels_an_order_already_cancelled():
    pool = OrderPool()
    pool.add_created("ord_1")
    pool.add_cancelled("ord_1")

    call = build_call(planned(event=EVENT_CANCEL_ALREADY_CANCELLED), pool)

    assert call.path == "/orders/ord_1/cancel"
    assert call.expected_status == 409
    assert call.fallback == ""


@pytest.mark.parametrize("event", [EVENT_READ_MISSING, EVENT_CANCEL_MISSING])
def test_an_unknown_identifier_is_never_one_the_run_created(event):
    pool = OrderPool()
    pool.add_created("ord_1")

    call = build_call(planned(event=event), pool)

    assert call.order_id != "ord_1"
    assert call.expected_status == 404


@pytest.mark.parametrize(
    "event", [EVENT_READ_VALID, EVENT_CANCEL_VALID, EVENT_CANCEL_ALREADY_CANCELLED]
)
def test_an_empty_pool_degrades_to_an_unknown_identifier(event):
    """Early in the run there is nothing to read yet; the row must stay honest."""
    call = build_call(planned(event=event), OrderPool())

    assert call.fallback == FALLBACK_POOL_EMPTY
    assert call.expected_status == 404


def test_the_pool_only_offers_identifiers_the_api_confirmed():
    pool = OrderPool()

    assert pool.pick_known(0) is None
    assert pool.take_open() is None
    assert pool.pick_cancelled(0) is None


# --- Dispatching the plan --------------------------------------------------


def test_every_planned_request_produces_exactly_one_record(config):
    plan = build_plan(config, run_id="r1")

    records = run_dispatch(config, plan, fake_orders_api())

    assert len(records) == len(plan)
    assert [record.request_id for record in records] == [
        request.request_id for request in plan
    ]


def test_every_request_carries_its_correlation_header(config):
    plan = build_plan(config, run_id="r1")
    handler = fake_orders_api()

    run_dispatch(config, plan, handler)

    sent_ids = [request.headers[REQUEST_ID_HEADER] for request in handler.journal]
    assert len(sent_ids) == len(plan)
    assert len(set(sent_ids)) == len(plan)
    assert set(sent_ids) == {request.request_id for request in plan}


def test_a_record_reports_what_was_intended_and_what_answered(config):
    plan = (planned(event=EVENT_CREATE_VALID),)

    record = run_dispatch(config, plan, fake_orders_api())[0]

    assert record.intended_event == EVENT_CREATE_VALID
    assert record.expected_status == 201
    assert record.status_code == 201
    assert record.result == RESULT_AS_EXPECTED
    assert record.client_latency_ms > 0
    assert record.scheduled_at <= record.sent_at


def test_the_recorded_latency_reflects_the_time_the_api_took(config):
    plan = (planned(),)

    record = run_dispatch(config, plan, fake_orders_api(latency_s=0.15))[0]

    assert record.client_latency_ms >= 150


def test_an_order_created_during_the_run_feeds_the_later_reads(config):
    plan = (
        planned(index=0, event=EVENT_CREATE_VALID, minute=0.0),
        planned(index=1, event=EVENT_READ_VALID, minute=1.0),
    )

    records = run_dispatch(config, plan, fake_orders_api())

    assert records[0].order_id.startswith("ord_")
    assert records[1].order_id == records[0].order_id
    assert records[1].fallback == ""


# --- Concurrency -----------------------------------------------------------


def test_requests_due_together_are_sent_concurrently(config):
    """Five 0.15 s responses must not add up to 0.75 s."""
    plan = tuple(planned(index=index) for index in range(5))

    started = time.perf_counter()
    records = run_dispatch(config, plan, fake_orders_api(latency_s=0.15))
    elapsed = time.perf_counter() - started

    assert len(records) == 5
    assert elapsed < 0.45, f"responses were awaited one after another ({elapsed:.2f}s)"


def test_a_slow_response_does_not_delay_the_next_scheduled_request(config):
    """The dispatcher waits for the clock, never for the previous response."""

    async def handler(request):
        if request.headers[REQUEST_ID_HEADER].endswith("000000"):
            await asyncio.sleep(0.4)
        return httpx.Response(201, json={"id": "ord_1"})

    plan = (
        planned(index=0, event=EVENT_CREATE_VALID, minute=0.0),
        planned(index=1, event=EVENT_CREATE_VALID, minute=1.0),
    )
    fast = config.with_overrides(seconds_per_minute=0.05)

    records = run_dispatch(fast, plan, handler)

    gap = (records[1].sent_at - records[0].sent_at).total_seconds()
    assert gap < 0.3, f"the second request waited for the first ({gap:.2f}s)"


def test_requests_wait_for_their_own_instant(config):
    plan = (
        planned(index=0, minute=0.0),
        planned(index=1, minute=10.0),
    )
    slow = config.with_overrides(seconds_per_minute=0.02)

    records = run_dispatch(slow, plan, fake_orders_api())

    gap = (records[1].sent_at - records[0].sent_at).total_seconds()
    assert gap >= 0.15, f"the second request was sent too early ({gap:.3f}s)"


def test_the_client_caps_its_pool_and_timeout_from_the_configuration(config):
    bounded = config.with_overrides(max_connections=7, timeout_s=3.5)

    limits = connection_limits(bounded)
    timeout = request_timeout(bounded)

    assert limits.max_connections == 7
    assert limits.max_keepalive_connections == 7
    assert timeout.read == 3.5
    assert timeout.connect == 3.5


def test_the_client_targets_the_configured_url(config):
    client = build_client(config)

    assert str(client.base_url) == config.target_url
    assert client.timeout == request_timeout(config)


def test_many_requests_overlap_on_one_client(config):
    depth = {"current": 0, "max": 0}

    async def handler(request):
        depth["current"] += 1
        depth["max"] = max(depth["max"], depth["current"])
        await asyncio.sleep(0.05)
        depth["current"] -= 1
        return httpx.Response(201, json={"id": "ord_1"})

    plan = tuple(planned(index=index) for index in range(12))

    async def runner():
        limited = config.with_overrides(max_connections=3)
        async with httpx.AsyncClient(
            base_url=limited.target_url,
            transport=httpx.MockTransport(handler),
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=3),
        ) as client:
            return await dispatch(client, limited, plan)

    records = asyncio.run(runner())

    assert len(records) == 12
    assert depth["max"] > 1, "nothing ran concurrently"


# --- Failures --------------------------------------------------------------


def test_a_timeout_is_recorded_without_losing_the_row(config):
    async def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    records = run_dispatch(config, (planned(),), handler)

    assert len(records) == 1
    record = records[0]
    assert record.status_code is None
    assert record.result == RESULT_TRANSPORT_ERROR
    assert "Timeout" in record.error
    assert record.client_latency_ms >= 0


def test_a_connection_failure_is_recorded_without_losing_the_row(config):
    async def handler(request):
        raise httpx.ConnectError("refused", request=request)

    record = run_dispatch(config, (planned(),), handler)[0]

    assert record.status_code is None
    assert record.result == RESULT_TRANSPORT_ERROR
    assert "ConnectError" in record.error


def test_an_unexpected_client_crash_still_produces_a_row(config):
    async def handler(request):
        raise RuntimeError("bug in the client")

    record = run_dispatch(config, (planned(),), handler)[0]

    assert record.status_code is None
    assert record.result == RESULT_TRANSPORT_ERROR
    assert "RuntimeError" in record.error


def test_no_row_is_lost_when_half_the_run_fails_at_transport_level(config):
    async def handler(request):
        if int(request.headers[REQUEST_ID_HEADER][-1]) % 2:
            raise httpx.ConnectTimeout("nope", request=request)
        return httpx.Response(201, json={"id": "ord_1"})

    plan = tuple(planned(index=index) for index in range(10))

    records = run_dispatch(config, plan, handler)

    assert len(records) == 10
    assert sum(r.result == RESULT_TRANSPORT_ERROR for r in records) == 5
    assert sum(r.result == RESULT_AS_EXPECTED for r in records) == 5


def test_a_server_failure_is_told_apart_from_an_intentional_client_error(config):
    plan = (
        planned(index=0, event=EVENT_CREATE_VALID),
        planned(index=1, event=EVENT_CREATE_INVALID_PAYLOAD, flaw="missing_amount"),
    )

    def status_for(request):
        return 500 if request.headers[REQUEST_ID_HEADER].endswith("000000") else 400

    records = run_dispatch(config, plan, fake_orders_api(status_for=status_for))

    assert records[0].result == RESULT_SERVER_ERROR
    assert records[0].intent == INTENT_VALID
    assert records[1].result == RESULT_AS_EXPECTED
    assert records[1].intent == INTENT_INVALID
    assert records[1].status_code == 400


def test_a_server_failure_on_an_intentional_error_is_still_a_server_failure(config):
    plan = (planned(event=EVENT_CREATE_INVALID_PAYLOAD, flaw="missing_amount"),)

    records = run_dispatch(config, plan, fake_orders_api(status_for=lambda _: 500))

    assert records[0].intent == INTENT_INVALID
    assert records[0].result == RESULT_SERVER_ERROR


def test_a_status_nobody_asked_for_is_flagged_as_unexpected(config):
    plan = (planned(event=EVENT_CREATE_VALID),)

    records = run_dispatch(config, plan, fake_orders_api(status_for=lambda _: 404))

    assert records[0].result == RESULT_UNEXPECTED


# --- The CSV ---------------------------------------------------------------


def test_the_csv_carries_the_fields_the_laboratory_requires():
    required = {
        "request_id",
        "scheduled_at",
        "sent_at",
        "operation",
        "intended_event",
        "status_code",
        "client_latency_ms",
    }

    assert required <= set(CSV_FIELDS)


def test_the_csv_holds_one_row_per_request_plus_a_header(tmp_path, config):
    plan = build_plan(config, run_id="r1")
    path = tmp_path / "requests.csv"

    with CsvRecorder(path) as recorder:
        run_dispatch(config, plan, fake_orders_api(), on_record=recorder.write)

    rows = list(csv.DictReader(path.read_text().splitlines()))
    assert len(rows) == len(plan)
    assert list(rows[0]) == list(CSV_FIELDS)
    assert {row["request_id"] for row in rows} == {r.request_id for r in plan}


def test_the_csv_lets_the_intent_be_compared_with_the_answer(tmp_path, config):
    plan = (planned(event=EVENT_CREATE_VALID),)
    path = tmp_path / "requests.csv"

    with CsvRecorder(path) as recorder:
        run_dispatch(
            config, plan, fake_orders_api(status_for=lambda _: 500), recorder.write
        )

    row = next(iter(csv.DictReader(path.read_text().splitlines())))
    assert row["intended_event"] == EVENT_CREATE_VALID
    assert row["expected_status"] == "201"
    assert row["status_code"] == "500"
    assert row["result"] == RESULT_SERVER_ERROR
    assert row["operation"] == OPERATION_CREATE


def test_a_transport_failure_leaves_an_empty_status_in_the_csv(tmp_path, config):
    async def handler(request):
        raise httpx.ConnectError("refused", request=request)

    path = tmp_path / "requests.csv"
    with CsvRecorder(path) as recorder:
        run_dispatch(config, (planned(),), handler, recorder.write)

    row = next(iter(csv.DictReader(path.read_text().splitlines())))
    assert row["status_code"] == ""
    assert row["result"] == RESULT_TRANSPORT_ERROR
    assert "ConnectError" in row["error"]


def test_the_timestamps_are_written_as_utc_instants(tmp_path, config):
    path = tmp_path / "requests.csv"
    with CsvRecorder(path) as recorder:
        run_dispatch(config, (planned(),), fake_orders_api(), recorder.write)

    row = next(iter(csv.DictReader(path.read_text().splitlines())))
    for field in ("scheduled_at", "sent_at"):
        moment = datetime.fromisoformat(row[field])
        assert moment.tzinfo is not None
        assert moment.utcoffset() == UTC.utcoffset(None)


def test_rows_reach_the_file_while_the_run_is_still_going(tmp_path, config):
    """A sixty minute run must survive being interrupted halfway."""
    path = tmp_path / "requests.csv"
    seen = []

    with CsvRecorder(path) as recorder:

        def write(record):
            recorder.write(record)
            seen.append(len(path.read_text().splitlines()))

        plan = tuple(planned(index=index) for index in range(5))
        run_dispatch(config, plan, fake_orders_api(), write)

    assert seen == [2, 3, 4, 5, 6], f"rows were buffered to the end: {seen}"


# --- Summary ---------------------------------------------------------------


def test_the_summary_counts_what_the_run_produced(config):
    plan = (
        planned(index=0, event=EVENT_CREATE_VALID),
        planned(index=1, event=EVENT_CREATE_INVALID_PAYLOAD, flaw="missing_amount"),
    )

    def status_for(request):
        return 400 if request.headers[REQUEST_ID_HEADER].endswith("000001") else None

    records = run_dispatch(config, plan, fake_orders_api(status_for=status_for))
    summary = summarise(records)

    assert summary["requests"] == 2
    assert summary["by_result"][RESULT_AS_EXPECTED] == 2
    assert summary["by_status"][201] == 1
    assert summary["by_status"][400] == 1
    assert summary["intentional_errors"] == 1
    assert summary["server_errors"] == 0
    assert summary["transport_errors"] == 0
    assert summary["latency_p50_ms"] > 0
    assert summary["latency_p95_ms"] >= summary["latency_p50_ms"]
