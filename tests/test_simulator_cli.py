"""The command line: overrides, the quick run and the no-traffic dry run.

A 60 minute run against a deployed API is expensive, so the entry point has to
make the small variant and the traffic-free inspection easy to reach.
"""

from __future__ import annotations

import pytest

from simulator.simulator import (
    ConfigError,
    build_plan,
    configure,
    describe_plan,
    load_config,
    main,
    parse_args,
)


def resolve(argv, lab_config_path):
    return configure(parse_args(["--config", str(lab_config_path), *argv]))


# --- Defaults --------------------------------------------------------------


def test_without_arguments_the_laboratory_configuration_is_used(lab_config_path):
    config = resolve([], lab_config_path)

    assert config.n_requests == 6000
    assert config.duration_seconds == 3600


def test_the_default_config_is_the_one_next_to_the_simulator(lab_config_path):
    args = parse_args([])

    assert args.config == lab_config_path


# --- The quick run ---------------------------------------------------------


def test_the_quick_run_sends_a_few_requests_in_a_few_seconds(lab_config_path):
    config = resolve(["--quick"], lab_config_path)

    assert config.n_requests == 30
    assert config.duration_seconds < 10


def test_the_quick_run_keeps_the_shape_of_the_experiment(lab_config_path):
    quick = resolve(["--quick"], lab_config_path)
    full = resolve([], lab_config_path)

    assert quick.mu_min == full.mu_min
    assert quick.sigma_min == full.sigma_min
    assert quick.invalid_share == full.invalid_share
    assert quick.scenarios == full.scenarios


def test_the_full_run_still_lasts_sixty_minutes(lab_config_path):
    config = resolve([], lab_config_path)

    assert config.duration_min == 60
    assert config.duration_seconds == 3600


# --- Overrides -------------------------------------------------------------


def test_explicit_flags_win_over_the_quick_preset(lab_config_path):
    config = resolve(["--quick", "--n-requests", "7"], lab_config_path)

    assert config.n_requests == 7
    assert config.duration_seconds < 10


@pytest.mark.parametrize(
    ("argv", "attribute", "expected"),
    [
        (
            ["--target-url", "https://api.example.com"],
            "target_url",
            "https://api.example.com",
        ),
        (["--n-requests", "120"], "n_requests", 120),
        (["--seconds-per-minute", "0.5"], "seconds_per_minute", 0.5),
        (["--seed", "7"], "seed", 7),
        (["--timeout", "2.5"], "timeout_s", 2.5),
        (["--max-connections", "9"], "max_connections", 9),
    ],
)
def test_each_flag_overrides_its_parameter(lab_config_path, argv, attribute, expected):
    config = resolve(argv, lab_config_path)

    assert getattr(config, attribute) == expected


def test_the_output_path_can_be_redirected(lab_config_path, tmp_path):
    target = tmp_path / "run.csv"

    config = resolve(["--output", str(target)], lab_config_path)

    assert config.output_csv == target


def test_an_override_that_breaks_the_experiment_is_rejected(lab_config_path):
    with pytest.raises(ConfigError, match="n_requests"):
        resolve(["--n-requests", "0"], lab_config_path)


# --- The dry run -----------------------------------------------------------


def test_a_dry_run_sends_nothing_and_writes_no_csv(tmp_path, capsys):
    target = tmp_path / "requests.csv"

    exit_code = main(
        [
            "--quick",
            "--dry-run",
            "--target-url",
            "http://127.0.0.1:1",
            "--output",
            str(target),
        ]
    )

    assert exit_code == 0
    assert not target.exists()
    assert "dry run" in capsys.readouterr().out.lower()


def test_the_dry_run_describes_the_traffic_it_would_send(lab_config_path):
    config = load_config(lab_config_path)
    plan = build_plan(config, run_id="dry")

    description = describe_plan(config, plan)

    assert "6000" in description
    assert "double_errors" in description
    assert str(config.output_csv) in description
    assert "create" in description


def test_a_missing_configuration_file_fails_without_a_traceback(tmp_path, capsys):
    exit_code = main(["--config", str(tmp_path / "absent.json")])

    assert exit_code == 2
    assert "absent.json" in capsys.readouterr().err
