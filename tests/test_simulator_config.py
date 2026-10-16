"""Configuration loading and validation for the traffic simulator.

The simulator must take every experiment parameter from ``simulator/config.json``,
so these tests pin both the laboratory values stored in that file and the
validation that rejects a configuration which would silently produce the wrong
experiment.
"""

from __future__ import annotations

import json

import pytest

from simulator.simulator import ConfigError, SimulatorConfig, load_config


@pytest.fixture
def lab_config(lab_config_path):
    return load_config(lab_config_path)


@pytest.fixture
def config_dict(lab_config_path):
    return json.loads(lab_config_path.read_text())


def write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return path


# --- The laboratory configuration file -------------------------------------


def test_lab_config_declares_the_laboratory_experiment_values(lab_config):
    assert lab_config.target_url == "http://localhost:8080"
    assert lab_config.n_requests == 6000
    assert lab_config.mu_min == 30
    assert lab_config.sigma_min == 10
    assert lab_config.invalid_share == 0.08
    assert lab_config.seed == 42


def test_lab_config_spans_the_sixty_minute_window_in_real_time(lab_config):
    assert lab_config.duration_min == 60
    assert lab_config.seconds_per_minute == 60
    assert lab_config.duration_seconds == 3600


def test_lab_config_declares_the_double_errors_scenario(lab_config):
    assert len(lab_config.scenarios) == 1
    scenario = lab_config.scenarios[0]
    assert scenario.start_min == 35
    assert scenario.end_min == 45
    assert scenario.effect == "double_errors"
    assert scenario.category == "electronics"


def test_lab_config_writes_the_csv_under_the_outputs_directory(lab_config):
    assert lab_config.output_csv.parts[-2:] == ("simulator", "requests.csv")
    assert lab_config.output_csv.is_absolute()


def test_lab_config_bounds_the_connection_pool_well_below_the_request_count(
    lab_config,
):
    assert 0 < lab_config.max_connections < lab_config.n_requests
    assert lab_config.timeout_s > 0


def test_lab_config_declares_a_quick_run_preset(lab_config):
    quick = lab_config.for_quick_run()

    assert quick.n_requests == 30
    assert quick.duration_seconds < 10
    assert quick.mu_min == lab_config.mu_min
    assert quick.sigma_min == lab_config.sigma_min


# --- Reading the file ------------------------------------------------------


def test_relative_output_paths_resolve_against_the_config_file(tmp_path, config_dict):
    config_dict["output_csv"] = "out/requests.csv"
    path = write_config(tmp_path, config_dict)

    config = load_config(path)

    assert config.output_csv == tmp_path / "out" / "requests.csv"


def test_a_missing_config_file_is_reported_as_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.json")


def test_a_malformed_config_file_is_reported_as_a_config_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")

    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(path)


def test_a_missing_required_key_names_the_key(tmp_path, config_dict):
    del config_dict["n_requests"]

    with pytest.raises(ConfigError, match="n_requests"):
        load_config(write_config(tmp_path, config_dict))


def test_an_unknown_key_is_rejected_instead_of_silently_ignored(tmp_path, config_dict):
    config_dict["mu_minutes"] = 30

    with pytest.raises(ConfigError, match="mu_minutes"):
        load_config(write_config(tmp_path, config_dict))


# --- Validation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("n_requests", 0, "n_requests"),
        ("n_requests", -1, "n_requests"),
        ("sigma_min", 0, "sigma_min"),
        ("sigma_min", -5, "sigma_min"),
        ("mu_min", -1, "mu_min"),
        ("mu_min", 61, "mu_min"),
        ("invalid_share", -0.1, "invalid_share"),
        ("invalid_share", 1.5, "invalid_share"),
        ("duration_min", 0, "duration_min"),
        ("seconds_per_minute", 0, "seconds_per_minute"),
        ("timeout_s", 0, "timeout_s"),
        ("max_connections", 0, "max_connections"),
        ("target_url", "localhost:8080", "target_url"),
        ("seed", 1.5, "seed"),
    ],
)
def test_out_of_range_values_are_rejected(tmp_path, config_dict, key, value, match):
    config_dict[key] = value

    with pytest.raises(ConfigError, match=match):
        load_config(write_config(tmp_path, config_dict))


def test_an_operation_mix_that_does_not_sum_to_one_is_rejected(tmp_path, config_dict):
    config_dict["operation_mix"] = {"create": 0.5, "read": 0.2, "cancel": 0.2}

    with pytest.raises(ConfigError, match="operation_mix"):
        load_config(write_config(tmp_path, config_dict))


def test_an_operation_mix_with_an_unknown_operation_is_rejected(tmp_path, config_dict):
    config_dict["operation_mix"] = {"create": 0.5, "read": 0.3, "delete": 0.2}

    with pytest.raises(ConfigError, match="delete"):
        load_config(write_config(tmp_path, config_dict))


def test_a_scenario_window_outside_the_run_is_rejected(tmp_path, config_dict):
    config_dict["scenarios"] = [
        {
            "start_min": 55,
            "end_min": 70,
            "effect": "double_errors",
            "category": "electronics",
        }
    ]

    with pytest.raises(ConfigError, match="end_min"):
        load_config(write_config(tmp_path, config_dict))


def test_an_inverted_scenario_window_is_rejected(tmp_path, config_dict):
    config_dict["scenarios"][0]["start_min"] = 45
    config_dict["scenarios"][0]["end_min"] = 35

    with pytest.raises(ConfigError, match="start_min"):
        load_config(write_config(tmp_path, config_dict))


def test_an_unknown_scenario_effect_is_rejected(tmp_path, config_dict):
    config_dict["scenarios"][0]["effect"] = "triple_errors"

    with pytest.raises(ConfigError, match="triple_errors"):
        load_config(write_config(tmp_path, config_dict))


def test_an_unknown_scenario_category_is_rejected(tmp_path, config_dict):
    config_dict["scenarios"][0]["category"] = "furniture"

    with pytest.raises(ConfigError, match="furniture"):
        load_config(write_config(tmp_path, config_dict))


# --- Error probability per segment -----------------------------------------


def test_the_base_error_probability_applies_outside_the_scenario_window(lab_config):
    assert lab_config.error_probability(20, "electronics") == pytest.approx(0.08)
    assert lab_config.error_probability(50, "electronics") == pytest.approx(0.08)


def test_the_scenario_doubles_the_error_probability_of_its_own_segment(lab_config):
    assert lab_config.error_probability(35, "electronics") == pytest.approx(0.16)
    assert lab_config.error_probability(40, "electronics") == pytest.approx(0.16)


def test_the_scenario_window_excludes_its_upper_bound(lab_config):
    assert lab_config.error_probability(45, "electronics") == pytest.approx(0.08)


def test_the_scenario_leaves_the_other_categories_untouched(lab_config):
    assert lab_config.error_probability(40, "books") == pytest.approx(0.08)
    assert lab_config.error_probability(40, "grocery") == pytest.approx(0.08)


def test_a_doubled_probability_is_never_allowed_past_certainty(tmp_path, config_dict):
    config_dict["invalid_share"] = 0.6
    config = load_config(write_config(tmp_path, config_dict))

    assert config.error_probability(40, "electronics") == pytest.approx(1.0)


# --- Overrides -------------------------------------------------------------


def test_overrides_produce_a_new_validated_configuration(lab_config):
    smaller = lab_config.with_overrides(n_requests=30, seconds_per_minute=0.05)

    assert smaller.n_requests == 30
    assert smaller.seconds_per_minute == 0.05
    assert lab_config.n_requests == 6000, "the original must stay untouched"
    assert isinstance(smaller, SimulatorConfig)


def test_an_invalid_override_is_rejected(lab_config):
    with pytest.raises(ConfigError, match="n_requests"):
        lab_config.with_overrides(n_requests=0)


def test_an_unknown_override_is_rejected(lab_config):
    with pytest.raises(ConfigError, match="nonsense"):
        lab_config.with_overrides(nonsense=1)
