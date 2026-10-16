"""Authenticating the simulator against a private function.

The deployed function grants no access to `allUsers`, so a caller has to prove
who it is. The minimum that needs: an `Authorization: Bearer <identity token>`
header on every request, with the token supplied from outside the process and
never written anywhere.

The token is deliberately NOT part of `SimulatorConfig`: a configuration object
is printed by `describe_plan`, dumped in a summary and easy to log by accident,
and a credential must not be able to travel that way.
"""

from __future__ import annotations

import asyncio
import csv

import httpx
import pytest
from conftest import planned_request as planned

from simulator.simulator import (
    REQUEST_ID_HEADER,
    CsvRecorder,
    auth_headers,
    build_client,
    configure,
    describe_plan,
    describe_run,
    dispatch,
    load_config,
    parse_args,
    resolve_auth_token,
    summarise,
)

TOKEN = "ey.aFakeIdentityTokenForTests.signature"


@pytest.fixture
def config(lab_config_path):
    return load_config(lab_config_path).with_overrides(
        n_requests=6, seconds_per_minute=0.002
    )


def run_with_headers(config, plan, headers):
    """Dispatch over a mock transport, returning the requests it received."""
    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "ord_1"})

    async def runner():
        async with httpx.AsyncClient(
            base_url=config.target_url,
            transport=httpx.MockTransport(handler),
            headers=headers,
        ) as client:
            return await dispatch(client, config, plan)

    records = asyncio.run(runner())
    return records, seen


# --- The header -----------------------------------------------------------


def test_no_token_means_no_authorization_header():
    assert auth_headers("") == {}
    assert auth_headers("   ") == {}


def test_a_token_becomes_a_bearer_header():
    assert auth_headers(TOKEN) == {"Authorization": f"Bearer {TOKEN}"}


def test_the_token_is_stripped_of_the_newline_gcloud_prints():
    assert auth_headers(f"  {TOKEN}\n") == {"Authorization": f"Bearer {TOKEN}"}


def test_the_token_is_already_a_bearer_value_only_once():
    """A caller who pastes `Bearer x` must not end up with `Bearer Bearer x`."""
    assert auth_headers(f"Bearer {TOKEN}") == {"Authorization": f"Bearer {TOKEN}"}


# --- On the wire ----------------------------------------------------------


def test_every_request_carries_the_token(config):
    plan = tuple(planned(index=i) for i in range(6))

    _, seen = run_with_headers(config, plan, auth_headers(TOKEN))

    assert len(seen) == 6
    assert all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in seen)


def test_the_correlation_header_survives_alongside_the_token(config):
    plan = (planned(index=0),)

    _, seen = run_with_headers(config, plan, auth_headers(TOKEN))

    assert seen[0].headers[REQUEST_ID_HEADER] == plan[0].request_id
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_without_a_token_nothing_is_sent(config):
    plan = (planned(index=0),)

    _, seen = run_with_headers(config, plan, auth_headers(""))

    assert "Authorization" not in seen[0].headers


def test_the_client_carries_the_token_as_a_default_header(config):
    client = build_client(config, auth_token=TOKEN)

    assert client.headers["authorization"] == f"Bearer {TOKEN}"


def test_the_client_sends_no_authorization_by_default(config):
    client = build_client(config)

    assert "authorization" not in client.headers


# --- The token must not leak ----------------------------------------------


def test_the_token_never_reaches_the_csv(tmp_path, config):
    plan = tuple(planned(index=i) for i in range(3))
    path = tmp_path / "requests.csv"

    async def handler(request):
        return httpx.Response(201, json={"id": "ord_1"})

    async def runner():
        async with httpx.AsyncClient(
            base_url=config.target_url,
            transport=httpx.MockTransport(handler),
            headers=auth_headers(TOKEN),
        ) as client:
            with CsvRecorder(path) as recorder:
                return await dispatch(client, config, plan, recorder.write)

    records = asyncio.run(runner())

    text = path.read_text()
    assert len(list(csv.DictReader(text.splitlines()))) == 3
    assert TOKEN not in text
    assert "Bearer" not in text
    assert all(TOKEN not in str(record) for record in records)


def test_the_token_is_absent_from_the_printed_plan(config, lab_config_path):
    from simulator.simulator import build_plan

    plan = build_plan(config, run_id="auth")

    description = describe_plan(config, plan)

    assert TOKEN not in description
    assert "Bearer" not in description


def test_the_token_is_absent_from_the_run_summary(config):
    plan = (planned(index=0),)
    records, _ = run_with_headers(config, plan, auth_headers(TOKEN))

    text = describe_run(summarise(records))

    assert TOKEN not in text
    assert "Bearer" not in text


def test_the_token_is_not_part_of_the_configuration(config):
    """A credential must not be reachable from the object that gets printed."""
    assert "auth" not in repr(config).lower()
    assert not hasattr(config, "auth_token")


# --- Where the token comes from -------------------------------------------


def test_the_token_can_be_passed_on_the_command_line(lab_config_path):
    args = parse_args(["--config", str(lab_config_path), "--auth-token", TOKEN])

    assert resolve_auth_token(args, {}) == TOKEN


def test_the_token_can_come_from_the_environment(lab_config_path):
    args = parse_args(["--config", str(lab_config_path)])

    token = resolve_auth_token(args, {"CLOUDPULSE_AUTH_TOKEN": TOKEN})

    assert token == TOKEN


def test_the_flag_wins_over_the_environment(lab_config_path):
    args = parse_args(["--config", str(lab_config_path), "--auth-token", "from-flag"])

    assert resolve_auth_token(args, {"CLOUDPULSE_AUTH_TOKEN": TOKEN}) == "from-flag"


def test_no_token_anywhere_means_unauthenticated(lab_config_path):
    args = parse_args(["--config", str(lab_config_path)])

    assert resolve_auth_token(args, {}) == ""


def test_the_token_does_not_change_the_rest_of_the_configuration(lab_config_path):
    with_token = configure(
        parse_args(["--config", str(lab_config_path), "--auth-token", TOKEN])
    )
    without = configure(parse_args(["--config", str(lab_config_path)]))

    assert with_token == without
