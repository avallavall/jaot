"""One definition of "binding" for the whole solver domain.

There used to be two, and they contradicted each other on screen. The exact
analysis called a constraint binding when its slack was zero — the standard
meaning of an *active* constraint. The adapters called it binding when its dual
was non-zero, which is a different statement: by complementary slackness a
non-zero dual implies zero slack, but **not** the other way round. A degenerate
optimum has active constraints priced at zero, and those are exactly the rows the
dual test drops.

Measured on real executions before the fix (2026-08-02), the disagreement was
systematic and always in the same direction — the dual test never marked a row the
slack test did not:

    execution              by dual     by slack
    exe_7750f4ac9992048a     2/3         3/3
    exe_59a247ca216c5dc3     0/21       13/21
    exe_2645dcc10c2cd185   316/685    398/685
    exe_62dd76a362cf3d10   295/450    300/450

So one panel reported *0 of 21 binding* for a model where 13 constraints sat
exactly on their limit. Slack is the definition; the dual is a price.

For a MIP there is a second trap. The duals come from an LP relaxation solved as a
separate model, whose solution is not the integer solution the user is shown, so
nothing computed there describes their result. Adapters report ``None`` for those
rows rather than answering a question about a different problem.
"""

# Below this, an activity counts as sitting on its limit. Shared so that the exact
# analysis and the adapters cannot drift into disagreeing by threshold either.
BINDING_EPS = 1e-6


def constraint_slack(activity: float, rhs: float, operator: str) -> float:
    """Signed room left over: ``0`` on the limit, positive when there is slack."""
    if operator in ("<=", "<"):
        return rhs - activity
    if operator in (">=", ">"):
        return activity - rhs
    return abs(activity - rhs)  # == : distance from equality


def is_binding(activity: float, rhs: float, operator: str, eps: float = BINDING_EPS) -> bool:
    """Whether the constraint sits on its limit at ``activity``."""
    return abs(constraint_slack(activity, rhs, operator)) < eps


def is_binding_within_bounds(
    activity: float,
    lhs: float,
    rhs: float,
    infinity: float,
    eps: float = BINDING_EPS,
) -> bool:
    """Same rule, for a solver that states a row as ``lhs <= a·x <= rhs``.

    SCIP and HiGHS encode the sense in the bounds — ``a·x <= b`` is
    ``-inf <= a·x <= b`` — so the operator is already in there and an infinite
    side simply cannot be touched.
    """
    if abs(rhs) < infinity and abs(activity - rhs) < eps:
        return True
    return abs(lhs) < infinity and abs(activity - lhs) < eps
