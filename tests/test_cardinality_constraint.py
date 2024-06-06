"""Tests for the continuous cardinality constraint."""

import numpy as np

from baybe.constraints.continuous import (
    ContinuousCardinalityConstraint,
    ContinuousLinearEqualityConstraint,
    ContinuousLinearInequalityConstraint,
)
from baybe.parameters.numerical import NumericalContinuousParameter
from baybe.recommenders.pure.nonpredictive.sampling import RandomRecommender
from baybe.searchspace.core import SearchSpace


def get_searchspace(n_param: int, min_nonzeros: int, max_nonzeros: int) -> SearchSpace:
    """Prepare a searchspace with cardinality constraints."""
    # parameters and constraints
    parameters = [
        NumericalContinuousParameter(name=f"x_{i}", bounds=(0, 1))
        for i in range(n_param)
    ]
    constraints = [
        ContinuousCardinalityConstraint(
            parameters=[f"x_{i}" for i in range(n_param)],
            cardinality_low=min_nonzeros,
            cardinality_up=max_nonzeros,
        )
    ]

    # search space
    searchspace = SearchSpace.from_product(parameters, constraints)
    return searchspace


def test_samples_random():
    """Random samples under cardinality and linear equality constraints."""
    # Settings
    N_PARAMETERS = 6
    MAX_NONZERO = 1
    MIN_NONZERO = 0
    N_POINTS = 10
    TOLERANCE = 1e-3
    RHS = 1.0

    # prepare search space
    parameters = [
        NumericalContinuousParameter(name=f"x_{i+1}", bounds=(0, 1))
        for i in range(N_PARAMETERS)
    ]

    # constraints
    constraints = [
        ContinuousLinearEqualityConstraint(
            parameters=["x_1", "x_2", "x_3", "x_4"],
            coefficients=[1.0, 1.0, 1.0, 1.0],
            rhs=RHS,
        ),
        ContinuousLinearInequalityConstraint(
            parameters=["x_1", "x_2", "x_5", "x_6"],
            coefficients=[1.0, 1.0, 1.0, 1.0],
            rhs=RHS,
        ),
        ContinuousCardinalityConstraint(
            parameters=["x_1", "x_2"],
            cardinality_up=MAX_NONZERO,
            cardinality_low=MIN_NONZERO,
        ),
    ]

    searchspace = SearchSpace.from_product(parameters, constraints)

    # draw samples
    samples = searchspace.continuous.samples_random(n_points=N_POINTS)

    # Assert that cardinality constraint is fulfilled
    n_nonzero = np.sum(~np.isclose(samples[["x_1", "x_2"]], 0.0), axis=1)
    assert np.all(n_nonzero >= MIN_NONZERO) and np.all(n_nonzero <= MAX_NONZERO)

    # linear equality constraint is fulfilled
    assert np.allclose(
        1.0 * samples["x_1"]
        + 1.0 * samples["x_2"]
        + 1.0 * samples["x_3"]
        + 1.0 * samples["x_4"],
        RHS,
        atol=TOLERANCE,
    )

    # linear non-equality constraint is fulfilled
    assert (
        (
            1.0 * samples["x_1"]
            + 1.0 * samples["x_2"]
            + 1.0 * samples["x_5"]
            + 1.0 * samples["x_6"]
        )
        .ge(RHS - TOLERANCE)
        .all()
    )

    # samples are not identical
    assert not (samples.nunique(axis=0) == 1).all()


def test_random_recommender_for_cardinality_constraint():
    """
    Recommendations generated by a Random recommendor under a cardinality constraint
    have the expected number of nonzero elements.
    """  # noqa
    # Settings
    N_PARAMETERS = 5
    MAX_NONZERO = 3
    MIN_NONZERO = 1
    BATCH_SIZE = 10

    # prepare search space
    searchspace = get_searchspace(N_PARAMETERS, MIN_NONZERO, MAX_NONZERO)

    # random recommender
    recommender = RandomRecommender()
    rec = recommender.recommend(
        searchspace=searchspace,
        batch_size=BATCH_SIZE,
    )

    # Assert that cardinality constraint is fulfilled
    n_nonzero = np.sum(~np.isclose(rec, 0.0), axis=1)
    assert np.all(n_nonzero >= MIN_NONZERO) and np.all(n_nonzero <= MAX_NONZERO)
