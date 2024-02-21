## Transfer Learning

# This example demonstrates BayBE's
# {doc}`Transfer Learning </userguide/transfer_learning>` capabilities:
# * We construct a campaign,
# * give it access to data from a related but different task,
# * and show how this additional information boosts optimization performance.

### Imports

import os
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import seaborn as sns
from botorch.test_functions.synthetic import Hartmann

from baybe import Campaign
from baybe.objective import Objective
from baybe.parameters import NumericalDiscreteParameter, TaskParameter
from baybe.searchspace import SearchSpace
from baybe.simulation import simulate_scenarios
from baybe.targets import NumericalTarget
from baybe.utils.botorch_wrapper import botorch_function_wrapper
from baybe.utils.plotting import create_example_plots

### Settings

# The following settings are used to set up the problem:

SMOKE_TEST = "SMOKE_TEST" in os.environ  # reduce the problem complexity in CI pipelines
DIMENSION = 3  # input dimensionality of the test function
BATCH_SIZE = 1  # batch size of recommendations per DOE iteration
N_MC_ITERATIONS = 5 if SMOKE_TEST else 75  # number of Monte Carlo runs
N_DOE_ITERATIONS = 5 if SMOKE_TEST else 10  # number of DOE iterations
POINTS_PER_DIM = 5 if SMOKE_TEST else 5  # number of grid points per input dimension

### Defining the Tasks

# For our example, we consider the "Hartmann" test function.
#
# More specifically, to demonstrate the transfer learning mechanism, we consider the
# problem of optimizing the function using training data from its negated version.
# The used model is of course not aware of this relationship but needs to infer it
# from the data gathered during the optimization process.

test_functions = {
    "Test_Function": botorch_function_wrapper(Hartmann(dim=DIMENSION)),
    "Training_Function": botorch_function_wrapper(Hartmann(dim=DIMENSION, negate=True)),
}

### Creating the Optimization Objective

# Both test functions have a single output that is to be minimized.
# The corresponding [Objective](baybe.objective.Objective)
# is created as follows:

objective = Objective(
    mode="SINGLE", targets=[NumericalTarget(name="Target", mode="MIN")]
)

### Creating the Searchspace

# The bounds of the search space are dictated by the test function:

BOUNDS = Hartmann(dim=DIMENSION).bounds

# First, we define one
# [NumericalDiscreteParameter](baybe.parameters.numerical.NumericalDiscreteParameter)
# per input dimension of the test function:

discrete_params = [
    NumericalDiscreteParameter(
        name=f"x{d}",
        values=np.linspace(lower, upper, POINTS_PER_DIM),
    )
    for d, (lower, upper) in enumerate(BOUNDS.T)
]

# ```{note}
# While we could optimize the function using
# [NumericalContinuousParameters](baybe.parameters.numerical.NumericalContinuousParameter),
# we use discrete parameters here because it lets us interpret the percentages shown in
# the final plot directly as the proportion of candidates for which there were target
# values revealed by the training function.
# ```

# Next, we define a
# [TaskParameter](baybe.parameters.categorical.TaskParameter) to encode the task context,
# which allows the model to establish a relationship between the training data and
# the data collected during the optimization process.
# Because we want to obtain recommendations only for the test function, we explicitly
# pass the `active_values` keyword.

task_param = TaskParameter(
    name="Function",
    values=["Test_Function", "Training_Function"],
    active_values=["Test_Function"],
)

# With the parameters at hand, we can now create our search space.

parameters = [*discrete_params, task_param]
searchspace = SearchSpace.from_product(parameters=parameters)

# (Lookup)=
### Generating Lookup Tables

# We generate two lookup tables containing the target values of both test
# functions at the given parameter grid.
# Parts of one lookup serve as the training data for the model.
# The other lookup is used as the loop-closing element, providing the target values of
# the test functions on demand.

grid = np.meshgrid(*[p.values for p in discrete_params])

lookups: Dict[str, pd.DataFrame] = {}
for function_name, function in test_functions.items():
    lookup = pd.DataFrame({f"x{d}": grid_d.ravel() for d, grid_d in enumerate(grid)})
    lookup["Target"] = lookup.apply(function, axis=1)
    lookup["Function"] = function_name
    lookups[function_name] = lookup
lookup_training_task = lookups["Training_Function"]
lookup_test_task = lookups["Test_Function"]

### Simulation Loop

# We now simulate campaigns for different amounts of training data unveiled,
# to show the impact of transfer learning on the optimization performance:

results: List[pd.DataFrame] = []
for p in (0.01, 0.02, 0.05, 0.08, 0.2):
    campaign = Campaign(searchspace=searchspace, objective=objective)
    initial_data = [lookup_training_task.sample(frac=p) for _ in range(N_MC_ITERATIONS)]
    result_fraction = simulate_scenarios(
        {f"{100*p}": campaign},
        lookup_test_task,
        initial_data=initial_data,
        batch_size=BATCH_SIZE,
        n_doe_iterations=N_DOE_ITERATIONS,
    )
    results.append(result_fraction)

# For comparison, we also optimize the function without using any initial data:

result_fraction = simulate_scenarios(
    {"0.0": Campaign(searchspace=searchspace, objective=objective)},
    lookup_test_task,
    batch_size=BATCH_SIZE,
    n_doe_iterations=N_DOE_ITERATIONS,
    n_mc_iterations=N_MC_ITERATIONS,
)
results = pd.concat([result_fraction, *results])

# All that remains is to visualize the results.
# As the example shows, the optimization speed can be significantly increased by
# using even small amounts of training data from related optimization tasks.

results.rename(columns={"Scenario": "% of data used"}, inplace=True)
path = Path(sys.path[0])
ax = sns.lineplot(
    data=results,
    marker="o",
    markersize=10,
    x="Num_Experiments",
    y="Target_CumBest",
    hue="% of data used",
)
create_example_plots(
    ax=ax,
    path=path,
    base_name="basic_transfer_learning",
)
