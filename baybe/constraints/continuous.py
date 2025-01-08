"""Continuous constraints."""

from __future__ import annotations

import gc
import math
from collections.abc import Collection, Iterator, Sequence
from itertools import combinations
from math import comb
from typing import TYPE_CHECKING, Any

import numpy as np
from attr.validators import gt, in_, lt
from attrs import define, field

from baybe.constraints.base import (
    CardinalityConstraint,
    ContinuousConstraint,
    ContinuousNonlinearConstraint,
)
from baybe.parameters import NumericalContinuousParameter
from baybe.utils.interval import Interval
from baybe.utils.numerical import DTypeFloatNumpy
from baybe.utils.validation import finite_float

if TYPE_CHECKING:
    from torch import Tensor

_valid_linear_constraint_operators = ["=", ">=", "<="]


@define
class ContinuousLinearConstraint(ContinuousConstraint):
    """Class for continuous linear constraints.

    Continuous linear constraints use parameter lists and coefficients to define
    in-/equality constraints over a continuous parameter space.
    """

    # object variables
    operator: str = field(validator=in_(_valid_linear_constraint_operators))
    """Defines the operator used in the equation. Internally this will negate rhs and
    coefficients for `<=`."""

    coefficients: list[float] = field()
    """In-/equality coefficient for each entry in ``parameters``."""

    rhs: float = field(default=0.0, converter=float, validator=finite_float)
    """Right-hand side value of the in-/equality."""

    @coefficients.validator
    def _validate_coefficients(  # noqa: DOC101, DOC103
        self, _: Any, coefficients: list[float]
    ) -> None:
        """Validate the coefficients.

        Raises:
            ValueError: If the number of coefficients does not match the number of
                parameters.
        """
        if len(self.parameters) != len(coefficients):
            raise ValueError(
                "The given 'coefficients' list must have one floating point entry for "
                "each entry in 'parameters'."
            )

    @coefficients.default
    def _default_coefficients(self):
        """Return equal weight coefficients as default."""
        return [1.0] * len(self.parameters)

    @property
    def _multiplier(self) -> float:
        """The internal multiplier for rhs and coefficients."""
        return -1.0 if self.operator == "<=" else 1.0

    @property
    def is_eq(self):
        """Whether this constraint models an equality (assumed inequality otherwise)."""
        return self.operator == "="

    def _drop_parameters(
        self, parameter_names: Collection[str]
    ) -> ContinuousLinearConstraint:
        """Create a copy of the constraint with certain parameters removed.

        Args:
            parameter_names: The names of the parameter to be removed.

        Returns:
            The reduced constraint.
        """
        parameters = [p for p in self.parameters if p not in parameter_names]
        coefficients = [
            c
            for p, c in zip(self.parameters, self.coefficients)
            if p not in parameter_names
        ]
        return ContinuousLinearConstraint(
            parameters, self.operator, coefficients, self.rhs
        )

    def to_botorch(
        self, parameters: Sequence[NumericalContinuousParameter], idx_offset: int = 0
    ) -> tuple[Tensor, Tensor, float]:
        """Cast the constraint in a format required by botorch.

        Used in calling ``optimize_acqf_*`` functions, for details see
        https://botorch.org/api/optim.html#botorch.optim.optimize.optimize_acqf

        Args:
            parameters: The parameter objects of the continuous space.
            idx_offset: Offset to the provided parameter indices.

        Returns:
            The tuple required by botorch.
        """
        import torch

        from baybe.utils.torch import DTypeFloatTorch

        param_names = [p.name for p in parameters]
        param_indices = [
            param_names.index(p) + idx_offset
            for p in self.parameters
            if p in param_names
        ]

        return (
            torch.tensor(param_indices),
            torch.tensor(
                [self._multiplier * c for c in self.coefficients], dtype=DTypeFloatTorch
            ),
            np.asarray(self._multiplier * self.rhs, dtype=DTypeFloatNumpy).item(),
        )


@define
class ContinuousCardinalityConstraint(
    CardinalityConstraint, ContinuousNonlinearConstraint
):
    """Class for continuous cardinality constraints."""

    relative_threshold: float = field(
        default=1e-2, converter=float, validator=[gt(0.0), lt(1.0)]
    )
    """A relative threshold for determining if the value is considered zero."""

    @property
    def n_inactive_parameter_combinations(self) -> int:
        """The number of possible inactive parameter combinations."""
        return sum(
            comb(len(self.parameters), n_inactive_parameters)
            for n_inactive_parameters in self._inactive_set_sizes()
        )

    def _inactive_set_sizes(self) -> range:
        """Get all possible sizes of inactive parameter sets."""
        return range(
            len(self.parameters) - self.max_cardinality,
            len(self.parameters) - self.min_cardinality + 1,
        )

    def inactive_parameter_combinations(self) -> Iterator[frozenset[str]]:
        """Get an iterator over all possible combinations of inactive parameters."""
        for n_inactive_parameters in self._inactive_set_sizes():
            yield from combinations(self.parameters, n_inactive_parameters)

    def sample_inactive_parameters(self, batch_size: int = 1) -> list[set[str]]:
        """Sample sets of inactive parameters according to the cardinality constraints.

        Args:
            batch_size: The number of parameter sets to be sampled.

        Returns:
            A list of sampled inactive parameter sets, where each set holds the
            corresponding parameter names.
        """
        # The number of possible parameter configuration per set cardinality
        n_configurations_per_cardinality = [
            math.comb(len(self.parameters), n)
            for n in range(self.min_cardinality, self.max_cardinality + 1)
        ]

        # Probability of each set cardinality under the assumption that all possible
        # inactive parameter sets are equally likely
        probabilities = n_configurations_per_cardinality / np.sum(
            n_configurations_per_cardinality
        )

        # Sample the number of active/inactive parameters
        n_active_params = np.random.choice(
            np.arange(self.min_cardinality, self.max_cardinality + 1),
            batch_size,
            p=probabilities,
        )
        n_inactive_params = len(self.parameters) - n_active_params

        # Sample the inactive parameters
        inactive_params = [
            set(np.random.choice(self.parameters, n_inactive, replace=False))
            for n_inactive in n_inactive_params
        ]

        return inactive_params

    def get_threshold(self, parameter: NumericalContinuousParameter) -> Interval:
        """Get the threshold values of a parameter.

        This method calculates the thresholds based on the parameter's bounds
        and the relative threshold.

        Note:
            Thresholds (lower, upper) are defined below:
            * If lower < 0 and upper > 0, any value v with lower < v < upper are treated
            zero;
            * If lower = 0 and upper > 0, any value v with lower <= v < upper are
            treated zero;
            * If lower < 0 and upper = 0, any value v with lower < v <= upper are
            treated zero.


        Args:
            parameter: The parameter object.

        Returns:
            The lower and upper thresholds.

        Raises:
            ValueError: when parameter_name is not present in parameter list of this
                constraint.
        """
        if parameter.name not in self.parameters:
            raise ValueError(
                f"The given parameter with name: {parameter.name} cannot "
                f"be found in the parameter list: {self.parameters}."
            )

        return Interval(
            lower=self.relative_threshold * parameter.bounds.lower,
            upper=self.relative_threshold * parameter.bounds.upper,
        )


# Collect leftover original slotted classes processed by `attrs.define`
gc.collect()
