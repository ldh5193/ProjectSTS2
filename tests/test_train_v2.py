"""Phase 4 tests — V2 training script helpers."""
from __future__ import annotations

import pytest

from scripts.train_v2 import parse_ascension_mix, resolve_device, make_env


def test_parse_mix_basic():
    mix = parse_ascension_mix("0:0.2,5:0.3,10:0.5")
    assert mix == {0: 0.2, 5: 0.3, 10: 0.5}


def test_parse_mix_single_level():
    assert parse_ascension_mix("10:1.0") == {10: 1.0}


def test_parse_mix_empty_returns_none():
    assert parse_ascension_mix("") is None
    assert parse_ascension_mix(None) is None


def test_parse_mix_whitespace_tolerant():
    assert parse_ascension_mix(" 0 : 0.5 , 10 : 0.5 ") == {0: 0.5, 10: 0.5}


def test_parse_mix_rejects_malformed():
    with pytest.raises(ValueError):
        parse_ascension_mix("0,5,10")  # no colons
    with pytest.raises(ValueError):
        parse_ascension_mix("99:1.0")  # ascension out of range
    with pytest.raises(ValueError):
        parse_ascension_mix("10:-0.5")  # negative weight


def test_resolve_device_explicit():
    assert resolve_device("cpu") == "cpu"
    # 'cuda' would require torch; just check we don't crash on the string
    assert resolve_device("cuda") in ("cuda",)


def test_resolve_device_auto():
    # auto returns one of cpu/cuda depending on the host. Just check
    # the string is one of the valid options.
    assert resolve_device("auto") in ("cpu", "cuda")


def test_resolve_device_rejects_bad_name():
    with pytest.raises(ValueError):
        resolve_device("tpu")


def test_make_env_with_mixture():
    env = make_env(ascension=0, ascension_mix={0: 0.5, 10: 0.5})
    obs, _ = env.reset(seed=42)
    # Just verify reset works end-to-end.
    assert obs.shape[0] > 0


def test_make_env_without_mixture():
    env = make_env(ascension=5, ascension_mix=None)
    obs, _ = env.reset(seed=42)
    assert env.unwrapped.rs.ascension == 5
