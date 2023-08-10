### Example for using the multi target mode for the objective

"""
Example for using the multi target mode for the objective.
It uses a desirability value to handle several targets.
"""

# This example assumes some basic familiarity with using BayBE.
# We thus refer to [`baybe_object`](./../Basics/baybe_object.md) for a basic example.

#### Necessary imports for this example

# This example assumes some basic familiarity with using BayBE.
# We thus refer to [`baybe_object`](./../Basics/baybe_object.md) for a basic example.

#### Necessary imports for this example

from baybe import BayBE
from baybe.parameters import CategoricalParameter, NumericalDiscreteParameter
from baybe.searchspace import SearchSpace
from baybe.targets import NumericalTarget, Objective
from baybe.utils import add_fake_results

#### Experiment setup and creating the searchspace

Categorical_1 = CategoricalParameter("Cat_1", values=[22, 33], encoding="OHE")
Categorical_2 = CategoricalParameter(
    "Cat_2",
    values=["very bad", "bad", "OK", "good", "very good"],
    encoding="INT",
)
Num_disc_1 = NumericalDiscreteParameter(
    "Num_disc_1", values=[1, 2, 3, 4, 6, 8, 10], tolerance=0.3
)
Num_disc_2 = NumericalDiscreteParameter(
    "Num_disc_2", values=[-1, -3, -6, -9], tolerance=0.3
)

parameters = [Categorical_1, Categorical_2, Num_disc_1, Num_disc_2]

searchspace = SearchSpace.from_product(parameters=parameters)


#### Defining the targets

# The multi target mode is handled when creating the objective object.
# Thus we first need to define the different targets.

# This examples has different targets with different modes.
# The first target is maximized and while the second one is minimized.
# Note that in this multi target mode, the user must specify bounds for each target.

Target_1 = NumericalTarget(
    name="Target_1", mode="MAX", bounds=(0, 100), bounds_transform_func="LINEAR"
)
Target_2 = NumericalTarget(
    name="Target_2", mode="MIN", bounds=(0, 100), bounds_transform_func="LINEAR"
)

# For each target it is also possible to specify a `bounds_transformation_func` function.
# A detailed discussion of this functionality can be found at the end of this example.

# In this example, define a third target working with the mode `MATCH`.
# We furthermore use `bounds_transform_func="BELL"`.

Target_3 = NumericalTarget(
    name="Target_3", mode="MATCH", bounds=(45, 55), bounds_transform_func="BELL"
)

# Note that the `MATCH` mode seeks to have the target at the mean between the two bounds.
# For example, choosing 95 and 105 will lead the algorithm seeking 100 as the optimal value.
# Thus, using the bounds, it is possible to control both the match target and
# the range around this target that is considered viable.


#### Creating the objective

# Now to work with these three targets the objective object must be properly created.
# The mode is set to `DESIRABILITY` and the targets are described in a list.

targets = [Target_1, Target_2, Target_3]

# As the recommender requires a single function, the different targets need to be combined.
# Thus, a `combine_function` is used to create a single target out of the several targets given.
# The combine function can either be the mean `MEAN` or the geometric mean `GEOM_MEAN`.
# Per default, `GEOM_MEAN` is used.
# Weights for each target can also be specified as a list of floats in the arguments
# Per default, weights are equally distributed between all targets and are normalized internally.
# It is thus not necessary to handle normalization or scaling.


objective = Objective(
    mode="DESIRABILITY",
    targets=targets,
    weights=[20, 20, 60],
    combine_func="MEAN",
)

print(objective)

#### Creating and printing the BayBE object

baybe_obj = BayBE(searchspace=searchspace, objective=objective)
print(baybe_obj)

#### Performing some iterations

# The following loop performs some recommendations and adds fake results.
# It also prints what happens to internal data.

N_ITERATIONS = 3

for kIter in range(N_ITERATIONS):
    print(f"\n\n##### ITERATION {kIter+1} #####")

    rec = baybe_obj.recommend(batch_quantity=3)
    print("\nRecommended measurements:\n", rec)

    add_fake_results(rec, baybe_obj)
    print("\nRecommended measurements with fake measured results:\n", rec)

    baybe_obj.add_measurements(rec)

    print("\n\nInternal measurement dataframe computational representation Y:\n")
    print(baybe_obj.measurements_targets_comp)


#### Addendum: Description of `bounds_transformation_func` functions

# This function is used to transform target values to the interval `[0,1]` for `MAX`/`MIN` mode.
# An ascending or decreasing `LINEAR` function is used per default.
# This function maps input values in a specified interval [lower, upper] to the interval `[0,1]`.
# Outside the specified interval, the function remains constant, that is, 0 or 1.

# For the match mode, two functions are available `TRIANGULAR` and `BELL`.
# The `TRIANGULAR` function is 0 outside a specified interval and linearly increases to 1 from both
# interval ends, reaching the value 1 at the center of the interval.
# This function is used per default for MATCH mode.
# The `BELL` function is a Gaussian bell curve, specified through the boundary values of the sigma
# interval, reaching the maximum value of 1 at the interval center.
