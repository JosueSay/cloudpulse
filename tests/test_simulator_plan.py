"""The deterministic plan: when each request leaves and what it intends to do.

The plan is generated before any socket is opened, so the whole shape of the
experiment — arrival curve, operation mix, intentional error share and the
``double_errors`` scenario — is verifiable without sending traffic.
"""

from __future__ import annotations

import statistics

import pytest

from simulator.simulator import (
    CATEGORIES,
    CUSTOMER_TIERS,
    EVENT_CANCEL_ALREADY_CANCELLED,
    EVENT_CANCEL_MISSING,
    EVENT_CANCEL_VALID,
    EVENT_CREATE_INVALID_PAYLOAD,
    EVENT_CREATE_VALID,
    EVENT_EXPECTED_STATUS,
    EVENT_READ_MISSING,
    EVENT_READ_VALID,
    INTENT_INVALID,
    INTENT_VALID,
    OPERATION_CANCEL,
    OPERATION_CREATE,
    OPERATION_READ,
    build_plan,
    load_config,
    order_payload,
)

RUN_ID = "testrun"


@pytest.fixture
def config(lab_config_path):
    return load_config(lab_config_path)


@pytest.fixture(scope="module")
def lab_plan(lab_config_path):
    """The full 6.000 request plan, generated once for the statistical tests."""
    return build_plan(load_config(lab_config_path), run_id=RUN_ID)


def share_of_invalid(requests):
    requests = list(requests)
    assert requests, "the segment under test must not be empty"
    return sum(r.intent == INTENT_INVALID for r in requests) / len(requests)


# --- Arrival instants ------------------------------------------------------


def test_the_plan_holds_exactly_the_configured_number_of_requests(lab_plan):
    assert len(lab_plan) == 6000


def test_every_instant_falls_inside_the_sixty_minute_window(lab_plan):
    assert all(0 <= request.scheduled_min <= 60 for request in lab_plan)


def test_the_instants_are_ordered_chronologically(lab_plan):
    minutes = [request.scheduled_min for request in lab_plan]

    assert minutes == sorted(minutes)


def test_the_indexes_follow_the_chronological_order(lab_plan):
    assert [request.index for request in lab_plan] == list(range(len(lab_plan)))


def test_the_arrival_curve_is_centred_on_the_configured_mean(lab_plan):
    minutes = [request.scheduled_min for request in lab_plan]

    assert statistics.fmean(minutes) == pytest.approx(30, abs=0.5)
    assert statistics.pstdev(minutes) == pytest.approx(10, abs=0.5)


def test_the_arrival_curve_is_a_bell_and_not_a_flat_line(lab_plan):
    buckets = [0] * 6
    for request in lab_plan:
        buckets[min(5, int(request.scheduled_min // 10))] += 1

    assert buckets.index(max(buckets)) == 3, f"peak outside minute 30: {buckets}"
    assert buckets[3] > 3 * buckets[0]
    assert buckets[3] > 3 * buckets[5]


def test_about_two_thirds_of_the_traffic_lands_within_one_sigma(lab_plan):
    inside = sum(20 <= request.scheduled_min <= 40 for request in lab_plan)

    assert inside / len(lab_plan) == pytest.approx(0.68, abs=0.03)


def test_instants_are_clipped_rather_than_dropped(config):
    """A window narrower than the bell keeps the request count exact.

    The scenario is dropped alongside the duration because a window may not
    outlive the run it belongs to.
    """
    narrow = build_plan(
        config.with_overrides(duration_min=30, scenarios=()), run_id=RUN_ID
    )

    assert len(narrow) == config.n_requests
    assert max(request.scheduled_min for request in narrow) == 30


def test_the_due_time_in_seconds_follows_the_time_scale(config):
    plan = build_plan(config.with_overrides(n_requests=10), run_id=RUN_ID)

    assert plan[0].due_seconds(config.seconds_per_minute) == pytest.approx(
        plan[0].scheduled_min * 60
    )
    fast = config.with_overrides(seconds_per_minute=0.05)
    assert plan[0].due_seconds(fast.seconds_per_minute) == pytest.approx(
        plan[0].scheduled_min * 0.05
    )


# --- Reproducibility -------------------------------------------------------


def test_the_same_seed_and_run_id_produce_an_identical_plan(config):
    first = build_plan(config.with_overrides(n_requests=200), run_id=RUN_ID)
    second = build_plan(config.with_overrides(n_requests=200), run_id=RUN_ID)

    assert first == second


def test_a_different_seed_produces_a_different_plan(config):
    small = config.with_overrides(n_requests=200)

    first = build_plan(small, run_id=RUN_ID)
    second = build_plan(small.with_overrides(seed=43), run_id=RUN_ID)

    assert [r.scheduled_min for r in first] != [r.scheduled_min for r in second]


def test_the_run_id_renames_the_requests_without_reshaping_the_experiment(config):
    small = config.with_overrides(n_requests=200)

    first = build_plan(small, run_id="aaa")
    second = build_plan(small, run_id="bbb")

    assert [r.request_id for r in first] != [r.request_id for r in second]
    assert [r.scheduled_min for r in first] == [r.scheduled_min for r in second]
    assert [r.intended_event for r in first] == [r.intended_event for r in second]


# --- Correlation identifiers -----------------------------------------------


def test_every_request_carries_a_unique_identifier(lab_plan):
    request_ids = [request.request_id for request in lab_plan]

    assert len(set(request_ids)) == len(request_ids)


def test_identifiers_survive_the_sanitising_the_api_applies(lab_plan):
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-")

    for request in (lab_plan[0], lab_plan[-1]):
        assert request.run_id in request.request_id
        assert len(request.request_id) <= 64
        assert set(request.request_id) <= allowed


# --- Operations and segments ----------------------------------------------


def test_the_operation_mix_follows_the_configuration(lab_plan):
    total = len(lab_plan)
    share = {
        operation: sum(r.operation == operation for r in lab_plan) / total
        for operation in (OPERATION_CREATE, OPERATION_READ, OPERATION_CANCEL)
    }

    assert share[OPERATION_CREATE] == pytest.approx(0.5, abs=0.03)
    assert share[OPERATION_READ] == pytest.approx(0.3, abs=0.03)
    assert share[OPERATION_CANCEL] == pytest.approx(0.2, abs=0.03)


def test_every_request_belongs_to_a_segment_of_the_api_schema(lab_plan):
    assert {r.category for r in lab_plan} == set(CATEGORIES)
    assert {r.customer_tier for r in lab_plan} == set(CUSTOMER_TIERS)


def test_every_amount_is_a_value_the_api_accepts(lab_plan):
    amounts = [r.amount for r in lab_plan]

    assert all(0 < amount <= 100_000 for amount in amounts)
    assert all(round(amount, 2) == amount for amount in amounts)


# --- Intentional errors ----------------------------------------------------


def test_the_intentional_error_share_matches_the_configuration(lab_plan):
    outside_scenario = [
        r
        for r in lab_plan
        if not (35 <= r.scheduled_min < 45 and r.category == "electronics")
    ]

    assert share_of_invalid(outside_scenario) == pytest.approx(0.08, abs=0.02)


def test_a_zero_share_plans_no_intentional_errors(config):
    plan = build_plan(config.with_overrides(invalid_share=0.0), run_id=RUN_ID)

    assert all(request.intent == INTENT_VALID for request in plan)


def test_a_full_share_plans_nothing_but_intentional_errors(config):
    plan = build_plan(config.with_overrides(invalid_share=1.0), run_id=RUN_ID)

    assert all(request.intent == INTENT_INVALID for request in plan)


def test_the_share_is_configurable_between_those_extremes(config):
    plan = build_plan(config.with_overrides(invalid_share=0.25), run_id=RUN_ID)
    unaffected = [r for r in plan if r.scenario == ""]

    assert share_of_invalid(unaffected) == pytest.approx(0.25, abs=0.03)


def test_the_three_families_of_intentional_error_are_all_planned(lab_plan):
    events = {r.intended_event for r in lab_plan if r.intent == INTENT_INVALID}

    assert EVENT_CREATE_INVALID_PAYLOAD in events, "no broken payloads"
    assert {EVENT_READ_MISSING, EVENT_CANCEL_MISSING} <= events, "no unknown ids"
    assert EVENT_CANCEL_ALREADY_CANCELLED in events, "no impossible sequences"


def test_each_event_keeps_the_status_the_api_contract_promises(lab_plan):
    for request in lab_plan:
        assert request.expected_status == EVENT_EXPECTED_STATUS[request.intended_event]


def test_valid_requests_plan_the_success_codes_of_the_three_operations(lab_plan):
    expected = {
        EVENT_CREATE_VALID: 201,
        EVENT_READ_VALID: 200,
        EVENT_CANCEL_VALID: 200,
    }
    for request in lab_plan:
        if request.intent == INTENT_VALID:
            assert expected[request.intended_event] == request.expected_status


def test_intentional_errors_plan_only_client_error_codes(lab_plan):
    for request in lab_plan:
        if request.intent == INTENT_INVALID:
            assert 400 <= request.expected_status < 500


# --- The double_errors scenario -------------------------------------------


def test_the_scenario_doubles_the_errors_of_its_segment(lab_plan):
    inside = [
        r
        for r in lab_plan
        if 35 <= r.scheduled_min < 45 and r.category == "electronics"
    ]
    outside = [
        r
        for r in lab_plan
        if not (35 <= r.scheduled_min < 45) and r.category == "electronics"
    ]

    assert share_of_invalid(inside) == pytest.approx(0.16, abs=0.05)
    assert share_of_invalid(inside) > 1.5 * share_of_invalid(outside)


def test_the_scenario_leaves_the_other_categories_at_the_base_share(lab_plan):
    others = [
        r
        for r in lab_plan
        if 35 <= r.scheduled_min < 45 and r.category != "electronics"
    ]

    assert share_of_invalid(others) == pytest.approx(0.08, abs=0.03)


def test_the_affected_requests_are_tagged_with_the_scenario(lab_plan):
    for request in lab_plan:
        inside = 35 <= request.scheduled_min < 45 and request.category == "electronics"
        assert request.scenario == ("double_errors" if inside else "")


def test_removing_the_scenario_removes_the_error_peak(config):
    plan = build_plan(config.with_overrides(n_requests=6000), run_id=RUN_ID)
    without = build_plan(
        config.with_overrides(n_requests=6000, scenarios=()), run_id=RUN_ID
    )

    def inside(requests):
        return [
            r
            for r in requests
            if 35 <= r.scheduled_min < 45 and r.category == "electronics"
        ]

    assert share_of_invalid(inside(plan)) > share_of_invalid(inside(without))
    assert share_of_invalid(inside(without)) == pytest.approx(0.08, abs=0.05)


# --- Payload construction --------------------------------------------------


def test_a_valid_create_sends_exactly_the_three_schema_fields(lab_plan):
    valid = next(r for r in lab_plan if r.intended_event == EVENT_CREATE_VALID)

    payload = order_payload(valid)

    assert payload == {
        "customer_tier": valid.customer_tier,
        "category": valid.category,
        "amount": valid.amount,
    }


def test_valid_requests_carry_no_payload_flaw(lab_plan):
    assert all(r.payload_flaw == "" for r in lab_plan if r.intent == INTENT_VALID)


def test_every_broken_create_declares_which_flaw_it_carries(lab_plan):
    broken = [r for r in lab_plan if r.intended_event == EVENT_CREATE_INVALID_PAYLOAD]

    assert broken, "the plan must contain broken payloads"
    assert all(r.payload_flaw for r in broken)
    assert len({r.payload_flaw for r in broken}) > 1, "only one kind of flaw"


def test_no_broken_payload_is_accidentally_valid(lab_plan):
    schema = {"customer_tier", "category", "amount"}

    for request in lab_plan:
        if request.intended_event != EVENT_CREATE_INVALID_PAYLOAD:
            continue
        payload = order_payload(request)
        if not isinstance(payload, dict):
            continue
        broken = (
            set(payload) != schema
            or payload.get("category") not in CATEGORIES
            or payload.get("customer_tier") not in CUSTOMER_TIERS
            or not isinstance(payload.get("amount"), (int, float))
            or isinstance(payload.get("amount"), bool)
            or not 0 < payload["amount"] <= 100_000
        )
        assert broken, f"{request.payload_flaw} would be accepted: {payload}"


def test_the_flaw_of_a_broken_payload_is_reproducible(config):
    small = config.with_overrides(n_requests=300, invalid_share=1.0)

    first = build_plan(small, run_id=RUN_ID)
    second = build_plan(small, run_id=RUN_ID)

    assert [r.payload_flaw for r in first] == [r.payload_flaw for r in second]
