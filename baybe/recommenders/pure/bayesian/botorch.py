"""Botorch recommender."""

import math
from typing import Any, ClassVar

import pandas as pd
from attr.converters import optional
from attrs import define, field

from baybe.exceptions import NoMCAcquisitionFunctionError
from baybe.recommenders.pure.bayesian.base import BayesianRecommender
from baybe.searchspace import (
    SearchSpace,
    SearchSpaceType,
    SubspaceContinuous,
    SubspaceDiscrete,
)
from baybe.utils.dataframe import to_tensor
from baybe.utils.sampling_algorithms import (
    DiscreteSamplingMethod,
    sample_numerical_df,
)

N_ITER_THRESHOLD = 10


@define(kw_only=True)
class BotorchRecommender(BayesianRecommender):
    """A pure recommender utilizing Botorch's optimization machinery.

    This recommender makes use of Botorch's ``optimize_acqf_discrete``,
    ``optimize_acqf`` and ``optimize_acqf_mixed`` functions to optimize discrete,
    continuous and hybrid search spaces, respectively. Accordingly, it can be applied to
    all kinds of search spaces.

    Note:
        In hybrid search spaces, the used algorithm performs a brute-force optimization
        that can be computationally expensive. Thus, the behavior of the algorithm in
        hybrid search spaces can be controlled via two additional parameters.
    """

    # Class variables
    compatibility: ClassVar[SearchSpaceType] = SearchSpaceType.HYBRID
    # See base class.

    # Object variables
    sequential_continuous: bool = field(default=False)
    """Flag defining whether to apply sequential greedy or batch optimization in
    **continuous** search spaces. (In discrete/hybrid spaces, sequential greedy
    optimization is applied automatically.)
    """

    hybrid_sampler: DiscreteSamplingMethod | None = field(
        converter=optional(DiscreteSamplingMethod), default=None
    )
    """Strategy used for sampling the discrete subspace when performing hybrid search
    space optimization."""

    sampling_percentage: float = field(default=1.0)
    """Percentage of discrete search space that is sampled when performing hybrid search
    space optimization. Ignored when ``hybrid_sampler="None"``."""

    @sampling_percentage.validator
    def _validate_percentage(  # noqa: DOC101, DOC103
        self, _: Any, value: float
    ) -> None:
        """Validate that the given value is in fact a percentage.

        Raises:
            ValueError: If ``value`` is not between 0 and 1.
        """
        if not 0 <= value <= 1:
            raise ValueError(
                f"Hybrid sampling percentage needs to be between 0 and 1 but is {value}"
            )

    def _recommend_discrete(
        self,
        subspace_discrete: SubspaceDiscrete,
        candidates_comp: pd.DataFrame,
        batch_size: int,
    ) -> pd.Index:
        """Generate recommendations from a discrete search space.

        Args:
            subspace_discrete: The discrete subspace from which to generate
                recommendations.
            candidates_comp: The computational representation of all discrete candidate
                points to be considered.
            batch_size: The size of the recommendation batch.

        Raises:
            NoMCAcquisitionFunctionError: If a non-Monte Carlo acquisition function is
                used with a batch size > 1.

        Returns:
            The dataframe indices of the recommended points in the provided
            computational representation.
        """
        # For batch size > 1, this optimizer needs a MC acquisition function
        if batch_size > 1 and not self.acquisition_function.is_mc:
            raise NoMCAcquisitionFunctionError(
                f"The '{self.__class__.__name__}' only works with Monte Carlo "
                f"acquisition functions for batch sizes > 1."
            )

        from botorch.optim import optimize_acqf_discrete

        # determine the next set of points to be tested
        candidates_tensor = to_tensor(candidates_comp)
        points, _ = optimize_acqf_discrete(
            self._botorch_acqf, batch_size, candidates_tensor
        )

        # retrieve the index of the points from the input dataframe
        # IMPROVE: The merging procedure is conceptually similar to what
        #   `SearchSpace._match_measurement_with_searchspace_indices` does, though using
        #   a simpler matching logic. When refactoring the SearchSpace class to
        #   handle continuous parameters, a corresponding utility could be extracted.
        idxs = pd.Index(
            pd.merge(
                candidates_comp.reset_index(),
                pd.DataFrame(points, columns=candidates_comp.columns),
                on=list(candidates_comp),
            )["index"]
        )

        return idxs

    def _recommend_continuous(
        self,
        subspace_continuous: SubspaceContinuous,
        batch_size: int,
    ) -> pd.DataFrame:
        """Generate recommendations from a continuous search space.

        Args:
            subspace_continuous: The continuous subspace from which to generate
                recommendations.
            batch_size: The size of the recommendation batch.

        Raises:
            NoMCAcquisitionFunctionError: If a non-Monte Carlo acquisition function is
                used with a batch size > 1.
            RuntimeError: If the combinatorial list of inactive parameters is None.

        Returns:
            A dataframe containing the recommendations as individual rows.
        """
        # For batch size > 1, this optimizer needs a MC acquisition function
        if batch_size > 1 and not self.acquisition_function.is_mc:
            raise NoMCAcquisitionFunctionError(
                f"The '{self.__class__.__name__}' only works with Monte Carlo "
                f"acquisition functions for batch sizes > 1."
            )

        import torch
        from botorch.optim import optimize_acqf
        from torch import Tensor

        def _recommend_continuous_with_inactive_parameters(
            _subspace_continuous: SubspaceContinuous,
            inactive_parameters: tuple[str, ...] | None = None,
        ) -> tuple[Tensor, Tensor]:
            """Define a helper function that can deal with inactive parameters."""
            if _subspace_continuous.constraints_cardinality:
                # When there are cardinality constraints present.
                if inactive_parameters is None:
                    # When no parameters are constrained to zeros
                    inactive_parameters = ()
                    fixed_parameters = None
                else:
                    # When certain parameters are constrained to zeros.

                    # Cast the inactive parameters to the format of fixed features used
                    # in optimize_acqf())
                    indices_inactive_params = [
                        _subspace_continuous.param_names.index(key)
                        for key in _subspace_continuous.param_names
                        if key in inactive_parameters
                    ]
                    fixed_parameters = {ind: 0.0 for ind in indices_inactive_params}

                # Create a new subspace by ensuring all active parameters are non-zeros
                _subspace_continuous = _subspace_continuous._ensure_nonzero_parameters(
                    inactive_parameters
                )
            else:
                # When there is no cardinality constraint
                fixed_parameters = None

            _points, _acqf_values = optimize_acqf(
                acq_function=self._botorch_acqf,
                bounds=torch.from_numpy(_subspace_continuous.param_bounds_comp),
                q=batch_size,
                num_restarts=5,  # TODO make choice for num_restarts
                raw_samples=10,  # TODO make choice for raw_samples
                fixed_features=fixed_parameters,
                equality_constraints=[
                    c.to_botorch(_subspace_continuous.parameters)
                    for c in _subspace_continuous.constraints_lin_eq
                ]
                or None,  # TODO: https://github.com/pytorch/botorch/issues/2042
                inequality_constraints=[
                    c.to_botorch(_subspace_continuous.parameters)
                    for c in _subspace_continuous.constraints_lin_ineq
                ]
                or None,  # TODO: https://github.com/pytorch/botorch/issues/2042
                sequential=self.sequential_continuous,
            )
            return _points, _acqf_values

        if len(subspace_continuous.constraints_cardinality):
            acqf_values_all: list[Tensor] = []
            points_all: list[Tensor] = []

            # The key steps of handling cardinality constraint are
            # * Determine several configurations of inactive parameters based on the
            # cardinality constraints.
            # * Optimize the acquisition function for different configurations and
            # pick the best one.
            # There are two mechanisms for the inactive parameter configurations. The
            # full list of different inactive parameter configurations is used,
            # when its size is not too large; otherwise we randomly pick a
            # fixed number of inactive parameter configurations.

            if (
                subspace_continuous.combinatorial_counts_zero_parameters
                > N_ITER_THRESHOLD
            ):
                # When the size of full list is too large, randomly set some
                # parameters inactive.
                for _ in range(N_ITER_THRESHOLD):
                    inactive_params_sample = (
                        subspace_continuous._sample_inactive_parameters(1)[0]
                    )

                    (
                        points_i,
                        acqf_values_i,
                    ) = _recommend_continuous_with_inactive_parameters(
                        subspace_continuous,
                        tuple(inactive_params_sample),
                    )

                    points_all.append(points_i.unsqueeze(0))
                    acqf_values_all.append(acqf_values_i.unsqueeze(0))

            elif subspace_continuous.combinatorial_zero_parameters is not None:
                # When the size of full list is not too large, iterate the combinations
                # of all possible inactive parameters.
                for (
                    inactive_params_generator
                ) in subspace_continuous.combinatorial_zero_parameters:
                    # flatten inactive parameters
                    inactive_params_sample = {
                        param
                        for sublist in inactive_params_generator
                        for param in sublist
                    }

                    (
                        points_i,
                        acqf_values_i,
                    ) = _recommend_continuous_with_inactive_parameters(
                        subspace_continuous,
                        tuple(inactive_params_sample),
                    )

                    points_all.append(points_i.unsqueeze(0))
                    acqf_values_all.append(acqf_values_i.unsqueeze(0))
            else:
                raise RuntimeError(
                    f"The attribute"
                    f"{SubspaceContinuous.combinatorial_zero_parameters.__name__}"
                    f"should not be None."
                )
            # Find the best option
            points = torch.cat(points_all)[torch.argmax(torch.cat(acqf_values_all)), :]
        else:
            # When there is no cardinality constraint
            points, _ = _recommend_continuous_with_inactive_parameters(
                subspace_continuous
            )

        # Return optimized points as dataframe
        rec = pd.DataFrame(points, columns=subspace_continuous.param_names)
        return rec

    def _recommend_hybrid(
        self,
        searchspace: SearchSpace,
        candidates_comp: pd.DataFrame,
        batch_size: int,
    ) -> pd.DataFrame:
        """Recommend points using the ``optimize_acqf_mixed`` function of BoTorch.

        This functions samples points from the discrete subspace, performs optimization
        in the continuous subspace with these points being fixed and returns the best
        found solution.
        **Important**: This performs a brute-force calculation by fixing every possible
        assignment of discrete variables and optimizing the continuous subspace for
        each of them. It is thus computationally expensive.

        Args:
            searchspace: The search space in which the recommendations should be made.
            candidates_comp: The computational representation of the candidates
                of the discrete subspace.
            batch_size: The size of the calculated batch.

        Raises:
            NoMCAcquisitionFunctionError: If a non-Monte Carlo acquisition function is
                used with a batch size > 1.

        Returns:
            The recommended points.
        """
        # For batch size > 1, this optimizer needs a MC acquisition function
        if batch_size > 1 and not self.acquisition_function.is_mc:
            raise NoMCAcquisitionFunctionError(
                f"The '{self.__class__.__name__}' only works with Monte Carlo "
                f"acquisition functions for batch sizes > 1."
            )

        import torch
        from botorch.optim import optimize_acqf_mixed

        if len(candidates_comp) > 0:
            # Calculate the number of samples from the given percentage
            n_candidates = math.ceil(
                self.sampling_percentage * len(candidates_comp.index)
            )

            # Potential sampling of discrete candidates
            if self.hybrid_sampler is not None:
                candidates_comp = sample_numerical_df(
                    candidates_comp, n_candidates, method=self.hybrid_sampler
                )

            # Prepare all considered discrete configurations in the
            # List[Dict[int, float]] format expected by BoTorch.
            # TODO: Currently assumes that discrete parameters are first and continuous
            #   second. Once parameter redesign [11611] is completed, we might adjust
            #   this.
            num_comp_columns = len(candidates_comp.columns)
            candidates_comp.columns = list(range(num_comp_columns))  # type: ignore
            fixed_features_list = candidates_comp.to_dict("records")
        else:
            fixed_features_list = None

        # Actual call of the BoTorch optimization routine
        points, _ = optimize_acqf_mixed(
            acq_function=self._botorch_acqf,
            bounds=torch.from_numpy(searchspace.param_bounds_comp),
            q=batch_size,
            num_restarts=5,  # TODO make choice for num_restarts
            raw_samples=10,  # TODO make choice for raw_samples
            fixed_features_list=fixed_features_list,
            equality_constraints=[
                c.to_botorch(
                    searchspace.continuous.parameters,
                    idx_offset=len(candidates_comp.columns),
                )
                for c in searchspace.continuous.constraints_lin_eq
            ]
            or None,  # TODO: https://github.com/pytorch/botorch/issues/2042
            inequality_constraints=[
                c.to_botorch(
                    searchspace.continuous.parameters,
                    idx_offset=num_comp_columns,
                )
                for c in searchspace.continuous.constraints_lin_ineq
            ]
            or None,  # TODO: https://github.com/pytorch/botorch/issues/2042
        )

        disc_points = points[:, :num_comp_columns]
        cont_points = points[:, num_comp_columns:]

        # Get selected candidate indices
        idxs = pd.Index(
            pd.merge(
                candidates_comp.reset_index(),
                pd.DataFrame(disc_points, columns=candidates_comp.columns),
                on=list(candidates_comp),
            )["index"]
        )

        # Get experimental representation of discrete and continuous parts
        rec_disc_exp = searchspace.discrete.exp_rep.loc[idxs]
        rec_cont_exp = pd.DataFrame(
            cont_points, columns=searchspace.continuous.param_names
        )

        # Adjust the index of the continuous part and create overall recommendations
        rec_cont_exp.index = rec_disc_exp.index
        rec_exp = pd.concat([rec_disc_exp, rec_cont_exp], axis=1)

        return rec_exp
