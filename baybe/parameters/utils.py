"""Parameter utilities."""

from collections.abc import Callable, Collection
from typing import Any, TypeVar

import pandas as pd
from attrs import evolve

from baybe.parameters.base import Parameter
from baybe.parameters.numerical import NumericalContinuousParameter

_TParameter = TypeVar("_TParameter", bound=Parameter)


def get_parameters_from_dataframe(
    df: pd.DataFrame,
    factory: Callable[[str, Collection[Any]], _TParameter],
    parameters: Collection[_TParameter] | None = None,
) -> list[_TParameter]:
    """Create a list of parameters from a dataframe.

    Returns one parameter for each column of the given dataframe. By default,
    the parameters are created using the provided factory, which takes the name
    of the column and its unique values as arguments. However, there is also
    the possibility to provide explicit parameter objects with names matching specific
    columns of the dataframe, to bypass the parameter factory creation for those
    columns. This allows finer control, for example, to specify custom parameter
    attributes (e.g. specific optional arguments) compared to what would be provided
    by the factory. Still, the pre-specified parameters are validated to ensure that
    they are compatible with the contents of the dataframe.

    Args:
        df: The dataframe from which to create the parameters.
        factory: A parameter factor, creating parameter objects for the columns
            from the column name and the unique column values.
        parameters: An optional list of parameter objects to bypass the factory
            creation for columns whose names match with the parameter names.

    Returns:
        The combined parameter list, containing both the (validated) pre-specified
        parameters and the parameters inferred from the dataframe.

    Raises:
        ValueError: If several parameters with identical names are provided.
        ValueError: If a parameter was specified for which no match was found.
    """
    # Turn the pre-specified parameters into a dict and check for duplicate names
    specified_params: dict[str, _TParameter] = {}
    if parameters is not None:
        for param in parameters:
            if param.name in specified_params:
                raise ValueError(
                    f"You provided several parameters with the name '{param.name}'."
                )
            specified_params[param.name] = param

    # Try to find a parameter match for each dataframe column
    parameters = []
    for name, series in df.items():
        assert isinstance(
            name, str
        ), "The given dataframe must only contain string-valued column names."
        unique_values = series.unique()

        # If a match is found, assert that the values are in range
        if match := specified_params.pop(name, None):
            if not all(match.is_in_range(x) for x in unique_values):
                raise ValueError(
                    f"The dataframe column '{name}' contains the values "
                    f"{unique_values}, which are outside the range of {match}."
                )
            parameters.append(match)

        # Otherwise, create a new parameter using the factory
        else:
            param = factory(name, unique_values)
            parameters.append(param)

    # By now, all pre-specified parameters must have been used
    if specified_params:
        raise ValueError(
            f"For the parameter(s) {list(specified_params.keys())}, "
            f"no match could be found in the given dataframe."
        )

    return parameters


def sort_parameters(parameters: Collection[Parameter]) -> tuple[Parameter, ...]:
    """Sort parameters alphabetically by their names."""
    return tuple(sorted(parameters, key=lambda p: p.name))


def activate_parameter(
    parameter: NumericalContinuousParameter,
) -> NumericalContinuousParameter:
    """Activates a given parameter by moving its bounds away from zero.

    Important:
        Parameters whose ranges include zero but whose bounds do not overlap with the
        inactive range (i.e. parameters that contain the value zero far from their
        boundary values) remain unchanged, because the corresponding activated parameter
        would no longer have a continuous value range.

    Args:
        parameter: The parameter to be activated.

    Returns:
        A copy of the parameter with adjusted bounds.

    Raises:
        ValueError: If the parameter cannot be activated since both its bounds are
            in the inactive range.
    """
    lower = parameter.bounds.lower
    upper = parameter.bounds.upper

    def in_inactive_range(x: float, /) -> bool:
        return -parameter.near_zero_threshold <= x <= parameter.near_zero_threshold

    # Upper bound is in inactive range
    if lower < -parameter.near_zero_threshold and in_inactive_range(upper):
        return evolve(parameter, bounds=(lower, -parameter.near_zero_threshold))

    # Lower bound is in inactive range
    if upper > parameter.near_zero_threshold and in_inactive_range(lower):
        return evolve(parameter, bounds=(parameter.near_zero_threshold, upper))

    # Both bounds in inactive range
    if in_inactive_range(lower) and in_inactive_range(upper):
        raise ValueError(
            f"Parameter '{parameter.name}' cannot be set active since its "
            f"bounds {parameter.bounds.to_tuple()} are entirely contained in the "
            f"inactive range [-{parameter.near_zero_threshold},"
            f" {parameter.near_zero_threshold}]."
        )

    # Both bounds separated from inactive range
    return parameter
