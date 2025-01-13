"""Tests for parameter utilities."""

import pytest
from pytest import param

from baybe.parameters import NumericalContinuousParameter
from baybe.parameters.numerical import _FixedNumericalContinuousParameter
from baybe.parameters.utils import activate_parameter
from baybe.utils.interval import Interval


def mirror_interval(interval: Interval) -> Interval:
    """Return an interval copy mirrored around the origin."""
    return Interval(lower=-interval.upper, upper=-interval.lower)


@pytest.mark.parametrize(
    (
        "bounds",
        "thresholds",
        "is_valid",
        "expected_bounds",
    ),
    [
        param(
            Interval(lower=-1.0, upper=1.0),
            Interval(lower=-1.0, upper=1.0),
            False,
            None,
            id="bounds_on_thresholds",
        ),
        param(
            Interval(lower=-1.0, upper=1.0),
            Interval(lower=-1.5, upper=1.5),
            False,
            None,
            id="bounds_in_thresholds",
        ),
        param(
            Interval(lower=-1.0, upper=1.0),
            Interval(lower=-1.5, upper=1.0),
            False,
            None,
            id="bounds_in_thresholds_single_side_match",
        ),
        param(
            Interval(lower=-1.0, upper=1.0),
            Interval(lower=-0.5, upper=0.5),
            True,
            Interval(lower=-1.0, upper=1.0),
            id="thresholds_in_bounds",
        ),
        param(
            Interval(lower=-1.0, upper=1.0),
            Interval(lower=-0.5, upper=1.0),
            True,
            Interval(lower=-1.0, upper=-0.5),
            id="thresholds_in_bounds_single_side_match",
        ),
        param(
            Interval(lower=-0.5, upper=1.0),
            Interval(lower=-1.0, upper=0.5),
            True,
            Interval(lower=0.5, upper=1.0),
            id="bounds_intersected_with_thresholds",
        ),
        param(
            Interval(lower=0.0, upper=1.0),
            Interval(lower=-1.0, upper=0.0),
            True,
            Interval(lower=0.0, upper=1.0),
            id="bounds_intersected_with_thresholds_on_one_point",
        ),
    ],
)
@pytest.mark.parametrize("mirror", [False, True])
def test_activate_parameter(
    bounds: Interval,
    thresholds: Interval,
    is_valid: bool,
    expected_bounds: Interval | None,
    mirror: bool,
) -> None:
    """Test that the utility correctly activate a parameter.

    Args:
        bounds: the bounds of the parameter to activate
        thresholds: the thresholds of inactive range
        is_valid: boolean variable indicating whether a parameter is returned from
            activate_parameter
        expected_bounds: the bounds of the activated parameter if one is returned
        mirror: if true both bounds and thresholds get mirrored

    Returns:
        None
    """
    if mirror:
        bounds = mirror_interval(bounds)
        thresholds = mirror_interval(thresholds)
    if mirror and is_valid:
        expected_bounds = mirror_interval(expected_bounds)

    parameter = NumericalContinuousParameter("parameter", bounds=bounds)

    if is_valid:
        activated_parameter = activate_parameter(parameter, thresholds)
        assert activated_parameter.bounds == expected_bounds
        if expected_bounds.is_degenerate:
            assert isinstance(activated_parameter, _FixedNumericalContinuousParameter)
    else:
        with pytest.raises(ValueError, match="cannot be set active"):
            activate_parameter(parameter, thresholds)


@pytest.mark.parametrize(
    ("bounds", "thresholds", "match"),
    [
        param(
            Interval(lower=-0.5, upper=0.5),
            Interval(lower=0.5, upper=1.0),
            "The thresholds must cover zero",
            id="invalid_thresholds",
        ),
        param(
            Interval(lower=0.5, upper=1.0),
            Interval(lower=-0.5, upper=0.5),
            "The parameter bounds must cover zero",
            id="invalid_bounds",
        ),
    ],
)
@pytest.mark.parametrize("mirror", [False, True])
def test_invalid_activate_parameter(
    bounds: Interval, thresholds: Interval, match: str, mirror: bool
) -> None:
    """Test that invalid bounds or thresholds are given.

    Args:
        bounds: the bounds of the parameter to activate
        thresholds: the thresholds of inactive range
        match: error message to match
        mirror: if true both bounds and thresholds get mirrored

    Returns:
        None
    """
    if mirror:
        bounds = mirror_interval(bounds)
        thresholds = mirror_interval(thresholds)

    parameter = NumericalContinuousParameter("parameter", bounds=bounds)
    with pytest.raises(ValueError, match=match):
        activate_parameter(parameter, thresholds)
