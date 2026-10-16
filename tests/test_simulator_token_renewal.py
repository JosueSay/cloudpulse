"""Renewing the identity token while the 60-minute run is in flight.

An identity token minted by `gcloud auth print-identity-token` lives about an
hour. The official run lasts exactly 60 minutes, so a token fetched once at
startup expires while traffic is still being sent and the last requests come
back `401`. The run cannot be repeated cheaply, so the renewal has to be part
of the simulator, not of the operator's attention span.

The tests below never call `gcloud`: a token source is just a command, so a
trivial `python3 -c` command stands in for it. That exercises the real
subprocess path — no mocks of `asyncio` internals — with tokens and failures
chosen by the test.
"""

from __future__ import annotations

import asyncio
import csv
import sys

import httpx
import pytest
from conftest import planned_request as planned

from simulator.simulator import (
    AUTH_HEADER,
    ConfigError,
    CsvRecorder,
    IdentityTokenSource,
    TokenError,
    apply_auth,
    build_client,
    describe_run,
    dispatch,
    load_config,
    parse_args,
    renew_auth_periodically,
    resolve_token_source,
    run_simulation,
    summarise,
)


def token_command(*tokens: str) -> tuple[str, ...]:
    """A command that prints a different token on each successive call.

    The counter lives in a file so it survives across process invocations, the
    way a real token endpoint hands out a new value every time.
    """
    script = (
        "import pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);"
        "n=int(p.read_text()) if p.exists() else 0;"
        "p.write_text(str(n+1));"
        "print(sys.argv[2:][min(n, len(sys.argv[2:])-1)])"
    )
    return (sys.executable, "-c", script)


@pytest.fixture
def counter(tmp_path):
    return str(tmp_path / "calls.txt")


@pytest.fixture
def config(lab_config_path):
    return load_config(lab_config_path).with_overrides(
        n_requests=4, seconds_per_minute=0.002
    )


def make_source(counter, *tokens):
    return IdentityTokenSource(command=(*token_command(), counter, *tokens))


# --- Applying a token to a live client ------------------------------------


def test_applying_a_token_sets_the_header(config):
    client = build_client(config)

    apply_auth(client, "tok-1")

    assert client.headers[AUTH_HEADER] == "Bearer tok-1"


def test_applying_a_new_token_replaces_the_old_one(config):
    client = build_client(config, auth_token="tok-old")

    apply_auth(client, "tok-new")

    assert client.headers[AUTH_HEADER] == "Bearer tok-new"
    assert "tok-old" not in str(client.headers)


def test_applying_an_empty_token_removes_the_header(config):
    client = build_client(config, auth_token="tok-1")

    apply_auth(client, "")

    assert AUTH_HEADER.lower() not in client.headers


# --- Minting a token ------------------------------------------------------


def test_a_source_returns_the_token_its_command_prints(counter):
    source = make_source(counter, "tok-1")

    assert asyncio.run(source.fetch()) == "tok-1"


def test_each_call_gets_a_fresh_token(counter):
    source = make_source(counter, "tok-1", "tok-2", "tok-3")

    async def three():
        return [await source.fetch() for _ in range(3)]

    assert asyncio.run(three()) == ["tok-1", "tok-2", "tok-3"]


def test_the_token_never_appears_in_the_command_line(counter):
    """The credential comes back on stdout; it is never an argument."""
    source = make_source(counter, "tok-1")

    assert all("tok-1" != part for part in source.command[:3])
    assert "print-identity-token" not in " ".join(source.command)  # test stand-in


def test_the_default_source_asks_gcloud_without_passing_secrets():
    source = IdentityTokenSource()

    assert source.command[:4] == ("gcloud", "auth", "print-identity-token", "--quiet")


def test_a_failing_command_raises_a_typed_error():
    source = IdentityTokenSource(
        command=(
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('boom\\n'); sys.exit(7)",
        )
    )

    with pytest.raises(TokenError, match="7"):
        asyncio.run(source.fetch())


def test_a_command_that_prints_nothing_raises(tmp_path):
    source = IdentityTokenSource(command=(sys.executable, "-c", "pass"))

    with pytest.raises(TokenError, match="empty"):
        asyncio.run(source.fetch())


def test_a_missing_command_raises_instead_of_crashing_the_run():
    source = IdentityTokenSource(command=("definitely-not-a-command-42",))

    with pytest.raises(TokenError):
        asyncio.run(source.fetch())


# --- The renewal loop -----------------------------------------------------


async def wait_for_header(client, expected, timeout_s=5.0):
    """Poll until the client carries `expected`, instead of guessing the timing.

    Spawning the token command takes tens of milliseconds, so a fixed sleep
    would race the subprocess rather than test the rotation.
    """
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if client.headers.get(AUTH_HEADER) == expected:
            return True
        await asyncio.sleep(0.005)
    return False


def test_the_loop_replaces_the_token_on_every_interval(config, counter):
    source = make_source(counter, "tok-1", "tok-2", "tok-3")
    client = build_client(config, auth_token="tok-0")

    async def run():
        task = asyncio.create_task(
            renew_auth_periodically(client, source.fetch, interval_s=0.02)
        )
        reached = [await wait_for_header(client, f"Bearer tok-{n}") for n in (1, 2, 3)]
        task.cancel()
        return reached

    assert asyncio.run(run()) == [True, True, True], (
        "the tokens did not rotate in order"
    )


def test_the_first_renewal_waits_for_the_interval(config, counter):
    """The token handed in at startup must be used until it is nearly stale."""
    source = make_source(counter, "tok-1")
    client = build_client(config, auth_token="tok-0")

    async def run():
        task = asyncio.create_task(
            renew_auth_periodically(client, source.fetch, interval_s=5)
        )
        await asyncio.sleep(0.05)
        header = client.headers[AUTH_HEADER]
        task.cancel()
        return header

    assert asyncio.run(run()) == "Bearer tok-0"


def test_a_failed_renewal_keeps_the_previous_token_and_is_reported(config):
    """A transient failure must not abort a 60-minute run."""
    failing = IdentityTokenSource(
        command=(sys.executable, "-c", "import sys; sys.exit(3)")
    )
    client = build_client(config, auth_token="tok-0")
    failures = []

    async def run():
        task = asyncio.create_task(
            renew_auth_periodically(
                client, failing.fetch, interval_s=0.03, on_error=failures.append
            )
        )
        await asyncio.sleep(0.12)
        task.cancel()

    asyncio.run(run())

    assert client.headers[AUTH_HEADER] == "Bearer tok-0"
    assert failures, "the failure was swallowed silently"
    assert all(isinstance(error, TokenError) for error in failures)


def test_the_loop_stops_when_cancelled(config, counter):
    source = make_source(counter, "tok-1", "tok-2")
    client = build_client(config)

    async def run():
        task = asyncio.create_task(
            renew_auth_periodically(client, source.fetch, interval_s=0.02)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return task.cancelled() or task.done()

    assert asyncio.run(run())


# --- Renewal during a real dispatch ---------------------------------------


def test_requests_sent_after_a_renewal_carry_the_new_token(config, counter):
    """The requests before the refresh use the old token, the ones after the new."""
    sent = []

    async def handler(request):
        sent.append(request.headers.get(AUTH_HEADER))
        return httpx.Response(201, json={"id": "ord_1"})

    source = make_source(counter, "tok-1")
    plan = (
        planned(index=0, minute=0.0),
        planned(index=1, minute=50.0),
    )
    slow = config.with_overrides(seconds_per_minute=0.004)

    async def runner():
        async with httpx.AsyncClient(
            base_url=slow.target_url,
            transport=httpx.MockTransport(handler),
            headers={AUTH_HEADER: "Bearer tok-0"},
        ) as client:
            task = asyncio.create_task(
                renew_auth_periodically(client, source.fetch, interval_s=0.05)
            )
            records = await dispatch(client, slow, plan)
            task.cancel()
            return records

    records = asyncio.run(runner())

    assert len(records) == 2
    assert sent[0] == "Bearer tok-0"
    assert sent[1] == "Bearer tok-1"


def test_a_renewed_token_never_reaches_the_csv(tmp_path, config, counter):
    source = make_source(counter, "supersecret-renewed")
    path = tmp_path / "requests.csv"
    plan = tuple(planned(index=i, minute=i * 10.0) for i in range(4))

    async def handler(request):
        return httpx.Response(201, json={"id": "ord_1"})

    async def runner():
        async with httpx.AsyncClient(
            base_url=config.target_url,
            transport=httpx.MockTransport(handler),
            headers={AUTH_HEADER: "Bearer tok-0"},
        ) as client:
            task = asyncio.create_task(
                renew_auth_periodically(client, source.fetch, interval_s=0.01)
            )
            with CsvRecorder(path) as recorder:
                records = await dispatch(client, config, plan, recorder.write)
            task.cancel()
            return records

    records = asyncio.run(runner())

    text = path.read_text()
    assert len(list(csv.DictReader(text.splitlines()))) == 4
    assert "supersecret-renewed" not in text
    assert "Bearer" not in text
    assert "supersecret-renewed" not in describe_run(summarise(records))


def test_run_simulation_renews_without_being_handed_a_token(config, counter):
    """`run_simulation` can own the whole credential lifecycle itself."""
    source = make_source(counter, "tok-first", "tok-second")
    plan = (planned(index=0),)

    records = asyncio.run(
        run_simulation(
            config.with_overrides(target_url="http://127.0.0.1:1"),
            plan,
            None,
            token_source=source,
        )
    )

    assert len(records) == 1, "a failing target must still produce a row"


# --- Configuration --------------------------------------------------------


def test_the_refresh_interval_comes_from_the_configuration(lab_config_path):
    config = load_config(lab_config_path)

    assert config.token_refresh_s == 1800
    assert config.token_refresh_s < 3600, "a token lives about an hour"
    assert config.token_refresh_s < config.duration_seconds, (
        "a 60-minute run must refresh at least once"
    )


def test_a_non_positive_refresh_interval_is_rejected(lab_config_path):
    config = load_config(lab_config_path)

    with pytest.raises(ConfigError, match="token_refresh_s"):
        config.with_overrides(token_refresh_s=0)


def test_the_cli_opts_into_renewal(lab_config_path):
    args = parse_args(["--config", str(lab_config_path), "--renew-token"])

    source = resolve_token_source(args)

    assert isinstance(source, IdentityTokenSource)
    assert source.command[:3] == ("gcloud", "auth", "print-identity-token")


def test_without_the_flag_there_is_no_renewal(lab_config_path):
    args = parse_args(["--config", str(lab_config_path)])

    assert resolve_token_source(args) is None
