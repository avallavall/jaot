# MDPDP-TW-T: Complete MIP Formulation

> **Multiple Depot Pickup and Delivery Problem with Soft Time Windows,
> Tachograph Constraints (EC 561/2006), and Vehicle Composition**
>
> Research document for JAOT solver integration. Designed for implementation
> as a Python generator producing `OptimizationProblem` JSON for the solver-agnostic backend.
>
> Date: 2026-04-01

---

## Table of Contents

1. [Problem Description](#1-problem-description)
2. [Sets and Indices](#2-sets-and-indices)
3. [Parameters](#3-parameters)
4. [Decision Variables](#4-decision-variables)
5. [Objective Function](#5-objective-function)
6. [Constraints: Core Routing](#6-constraints-core-routing)
7. [Constraints: Capacity](#7-constraints-capacity)
8. [Constraints: Soft Time Windows](#8-constraints-soft-time-windows)
9. [Constraints: Tachograph (EC 561/2006)](#9-constraints-tachograph-ec-5612006)
10. [Constraints: Vehicle Composition](#10-constraints-vehicle-composition)
11. [Tachograph Modeling Approach](#11-tachograph-modeling-approach)
12. [Tractability Analysis](#12-tractability-analysis)
13. [Recommended Simplifications](#13-recommended-simplifications)
14. [Implementation Notes for JAOT](#14-implementation-notes-for-jaot)
15. [References](#15-references)

---

## 1. Problem Description

A transport company operates a heterogeneous fleet where each physical vehicle
is a composition of **tractor + trailer + driver**. Each vehicle starts at a
specific depot. Orders consist of paired pickup-delivery requests: the same
vehicle must visit the pickup node and then the delivery node. The company
wants to minimize total transportation cost while penalizing unserved orders.

**Extensions over the base MDPDP:**

1. **Soft Time Windows** -- Each node has a preferred time window. Late arrival
   is permitted but incurs a steep penalty proportional to the tardiness.
2. **Spanish/EU Tachograph (EC 561/2006)** -- Drivers must respect mandatory
   break and rest regulations: 4.5h max continuous driving before a 45min
   break, 9h max daily driving (extendable to 10h twice per week), daily
   and weekly rest periods.
3. **Vehicle Composition** -- Tractors, trailers, and drivers are separate
   resources with compatibility constraints. A "vehicle" is formed by
   assigning one compatible tractor, one compatible trailer, and one
   qualified driver.

---

## 2. Sets and Indices

### 2.1 Node Sets

| Symbol | Description |
|--------|-------------|
| O = {o_1, ..., o_m} | Depot origin nodes (one per physical depot) |
| E = {e_1, ..., e_m} | Depot endpoint nodes (vehicles return here) |
| P = {p_1, ..., p_n} | Pickup nodes (one per order) |
| D = {d_1, ..., d_n} | Delivery nodes (one per order) |
| N = O + P + D + E | All nodes |
| C = P + D | Customer nodes (pickup + delivery) |

Each order i in {1, ..., n} has a pickup node p_i in P and a delivery
node d_i in D. We use the notation pair(p_i) = d_i and pair(d_i) = p_i.

### 2.2 Vehicle and Resource Sets

| Symbol | Description |
|--------|-------------|
| K = {1, ..., m} | Set of available vehicles (routes) |
| TR = {1, ..., n_tr} | Set of tractors |
| TL = {1, ..., n_tl} | Set of trailers |
| DR = {1, ..., n_dr} | Set of drivers |
| COMP_TR_TL subset TR x TL | Compatible tractor-trailer pairs |
| COMP_DR_TR subset DR x TR | Compatible driver-tractor pairs |
| QUAL_DR_i subset DR | Drivers qualified for order i |

Each vehicle k in K is associated with an origin depot o_k and an
endpoint depot e_k. The vehicle composition assigns exactly one tractor,
one trailer, and one driver to each active vehicle.

### 2.3 Tachograph Segment Sets

| Symbol | Description |
|--------|-------------|
| B = {1, ..., b_max} | Set of driving segments within a daily shift |
| W = {1, ..., 7} | Days in the planning week |

A driving segment is a period of continuous driving between two
mandatory breaks. Within a daily shift, a driver has at most b_max
segments (typically b_max = 3, since 9h / 4.5h = 2 full segments
plus a possible partial third).

---

## 3. Parameters

### 3.1 Network Parameters

| Symbol | Description | Unit |
|--------|-------------|------|
| t_{ij} | Travel time from node i to node j | hours |
| c_{ij} | Travel distance from node i to node j | km |
| s_i | Service time at node i | hours |
| q_i | Load change at node i: +q for pickup, -q for delivery | pallets |

### 3.2 Vehicle Parameters

| Symbol | Description | Unit |
|--------|-------------|------|
| Q_k | Capacity of vehicle k (determined by trailer) | pallets |
| f_k | Fuel consumption rate per km of vehicle k | EUR/km |
| D_max_k | Maximum distance for vehicle k per day | km |

### 3.3 Time Window Parameters

| Symbol | Description | Unit |
|--------|-------------|------|
| a_i | Earliest service start time at node i | hours |
| b_i | Latest desired service start time at node i | hours |
| beta | Penalty cost per hour of tardiness (VERY HIGH) | EUR/h |

### 3.4 Objective Weights

| Symbol | Description |
|--------|-------------|
| alpha | Weight for transportation cost |
| gamma | Penalty per unserved order |

### 3.5 Tachograph Parameters (EC 561/2006)

| Symbol | Value | Description |
|--------|-------|-------------|
| T_drive_max | 4.5 h | Max continuous driving before mandatory break |
| T_break_min | 0.75 h (45 min) | Minimum mandatory break duration |
| T_break_split_1 | 0.25 h (15 min) | First part of split break |
| T_break_split_2 | 0.50 h (30 min) | Second part of split break |
| T_daily_drive | 9.0 h | Standard max daily driving time |
| T_daily_drive_ext | 10.0 h | Extended daily driving (max 2x/week) |
| T_daily_rest | 11.0 h | Standard daily rest period |
| T_daily_rest_red | 9.0 h | Reduced daily rest (max 3x between weekly rests) |
| T_weekly_drive | 56.0 h | Max weekly driving time |
| T_biweekly_drive | 90.0 h | Max bi-weekly driving time |
| T_weekly_rest | 45.0 h | Standard weekly rest |
| T_weekly_rest_red | 24.0 h | Reduced weekly rest (compensate in 3 weeks) |

### 3.6 Big-M Constants

| Symbol | Description |
|--------|-------------|
| M_time | Large constant for time big-M (= max planning horizon) |
| M_load | Large constant for load big-M (= max vehicle capacity) |
| M_drive | Large constant for driving big-M (= T_daily_drive_ext) |

**Setting M values:** Use the tightest possible values.
- M_time = b_max_node + max(t_{ij}) + max(s_i), i.e., the latest
  possible arrival at any node plus worst-case travel.
- M_load = max_k(Q_k).
- M_drive = T_daily_drive_ext = 10.0.

---

## 4. Decision Variables

### 4.1 Core Routing Variables

| Variable | Type | Description |
|----------|------|-------------|
| X_{ijk} | Binary | 1 if vehicle k travels directly from node i to node j |
| Z_i | Binary | 1 if order i is NOT served (penalty variable) |

### 4.2 Time and Load Variables

| Variable | Type | Domain | Description |
|----------|------|--------|-------------|
| S_{ik} | Continuous | >= 0 | Arrival/start-of-service time at node i by vehicle k |
| L_{ik} | Continuous | >= 0 | Current load of vehicle k upon departing node i |
| T_i | Continuous | >= 0 | Tardiness at node i (late arrival beyond b_i) |

### 4.3 Tachograph Variables

| Variable | Type | Domain | Description |
|----------|------|--------|-------------|
| H_{ik} | Continuous | [0, T_drive_max] | Cumulative driving time in current segment when vehicle k arrives at node i |
| R_{ijk} | Binary | {0,1} | 1 if vehicle k takes a mandatory break on arc (i,j) |
| W_{ik} | Continuous | >= 0 | Total daily driving accumulated when vehicle k arrives at node i |
| E_k | Binary | {0,1} | 1 if vehicle k uses extended daily driving (10h instead of 9h) |

### 4.4 Vehicle Composition Variables

| Variable | Type | Description |
|----------|------|-------------|
| Y_k | Binary | 1 if vehicle k is used (at least one order assigned) |
| A^TR_{tk} | Binary | 1 if tractor t is assigned to vehicle k |
| A^TL_{lk} | Binary | 1 if trailer l is assigned to vehicle k |
| A^DR_{dk} | Binary | 1 if driver d is assigned to vehicle k |

---

## 5. Objective Function

```
Minimize:
    alpha * SUM_{i in N} SUM_{j in N} SUM_{k in K} (c_{ij} * f_k * X_{ijk})
  + beta  * SUM_{i in C} T_i
  + gamma * SUM_{i=1}^{n} Z_i
```

**Three components:**
1. **Transportation cost:** distance * fuel rate, summed over all arcs used.
2. **Tardiness penalty:** beta * total hours of late arrivals (soft TW).
3. **Unserved order penalty:** gamma per order not delivered.

The penalty beta should be set very high (e.g., 10x the average order
transport cost) to make tardiness extremely undesirable but still
feasible as a last resort. The penalty gamma should be even higher
(e.g., 100x average cost) to strongly discourage leaving orders unserved.

---

## 6. Constraints: Core Routing

### C1. Each served order is visited exactly once (pickup)

```
SUM_{k in K} SUM_{j in N} X_{p_i,j,k} = 1 - Z_i        for all i in {1..n}
```

If Z_i = 0 (order served), exactly one vehicle visits the pickup.
If Z_i = 1 (order unserved), no vehicle visits it.

### C2. Each served order is visited exactly once (delivery)

```
SUM_{k in K} SUM_{j in N} X_{d_i,j,k} = 1 - Z_i        for all i in {1..n}
```

### C3. Same vehicle serves pickup and delivery (pairing)

```
SUM_{j in N} X_{p_i,j,k} = SUM_{j in N} X_{d_i,j,k}    for all i in {1..n}, k in K
```

If vehicle k visits pickup p_i, it must also visit delivery d_i.

### C4. Flow conservation at customer nodes

```
SUM_{i in N} X_{i,h,k} = SUM_{j in N} X_{h,j,k}         for all h in C, k in K
```

What flows into a customer node must flow out.

### C5. Vehicle departs from its origin depot

```
SUM_{j in N} X_{o_k,j,k} = Y_k                           for all k in K
```

Vehicle k leaves its depot if and only if it is used.

### C6. Vehicle arrives at its endpoint depot

```
SUM_{i in N} X_{i,e_k,k} = Y_k                           for all k in K
```

### C7. Vehicles only use their own depots

```
X_{o_l,j,k} = 0   for all l != k, j in N, k in K        (cannot leave others' depots)
X_{i,e_l,k} = 0   for all l != k, i in N, k in K        (cannot arrive at others' endpoints)
```

### C8. Precedence: pickup before delivery

```
S_{p_i,k} + s_{p_i} + t_{p_i,d_i} <= S_{d_i,k} + M_time * (1 - SUM_{j in N} X_{p_i,j,k})
                                                           for all i in {1..n}, k in K
```

If vehicle k serves order i, it must visit the pickup before the delivery.

### C9. No self-loops

```
X_{i,i,k} = 0                                             for all i in N, k in K
```

---

## 7. Constraints: Capacity

### C10. Load tracking (MTZ-style)

```
L_{ik} + q_j - M_load * (1 - X_{ijk}) <= L_{jk}          for all i,j in C, k in K
L_{ik} + q_j + M_load * (1 - X_{ijk}) >= L_{jk}          for all i,j in C, k in K
```

These two constraints together force: if X_{ijk} = 1, then L_{jk} = L_{ik} + q_j.
When X_{ijk} = 0, the constraints are relaxed by big-M.

### C11. Load bounds

```
0 <= L_{ik} <= Q_k                                         for all i in C, k in K
```

Load must be non-negative and within the vehicle's capacity at all times.

### C12. Initial load at depot is zero

```
L_{o_k,k} = 0                                             for all k in K
```

### C13. Maximum distance per vehicle

```
SUM_{i in N} SUM_{j in N} c_{ij} * X_{ijk} <= D_max_k    for all k in K
```

---

## 8. Constraints: Soft Time Windows

### C14. Time propagation (big-M linearization)

```
S_{ik} + s_i + t_{ij} - M_time * (1 - X_{ijk}) <= S_{jk}
                                       for all i in N, j in N, k in K, i != j
```

If vehicle k travels from i to j, the arrival at j must be at least the
departure from i (arrival + service + travel time).

### C15. Earliest arrival (hard lower bound)

```
S_{ik} >= a_i * (1 - Z_{ceil(i)})     for all i in C, k in K
```

A vehicle cannot arrive before the time window opens (this is hard --
early arrival means waiting, which is free).

Note: `ceil(i)` maps node i back to its order index. For pickup p_i
and delivery d_i, both map to order i.

### C16. Tardiness definition

```
T_i >= S_{ik} - b_i - M_time * (1 - SUM_{j in N} X_{i,j,k})
                                       for all i in C, k in K
```

If vehicle k visits node i, tardiness T_i >= (arrival - latest desired).
If the arrival is on time, T_i can be 0 (driven to 0 by minimization).

### C17. Tardiness non-negativity

```
T_i >= 0                               for all i in C
```

---

## 9. Constraints: Tachograph (EC 561/2006)

This is the most complex component. We use a **continuous-time segment
tracking** approach with auxiliary binary variables to track driving
hours between breaks.

### 9.1 Driving Segment Tracking

The key idea: variable H_{ik} tracks how many hours the driver of
vehicle k has been driving continuously (since last break) when
arriving at node i. When H_{ik} approaches T_drive_max (4.5h), a
break must be taken.

#### C18. Segment accumulation on arcs

```
H_{jk} >= H_{ik} + t_{ij} - M_drive * (1 - X_{ijk}) - M_drive * R_{ijk}
                                       for all i,j in N, k in K, i != j
```

If vehicle k travels from i to j WITHOUT a break (R_{ijk}=0), the
continuous driving time accumulates. If a break is taken (R_{ijk}=1),
the constraint is relaxed (driver resets after break).

#### C19. Segment reset after break

```
H_{jk} <= t_{ij} + M_drive * (1 - R_{ijk})
                                       for all i,j in N, k in K where X_{ijk} can be 1
```

If a break is taken on arc (i,j), then H_{jk} = t_{ij} (only the
driving AFTER the break counts). If no break (R_{ijk}=0), this
constraint is relaxed.

More precisely, if R_{ijk}=1 and X_{ijk}=1: the driver drives some
portion of arc (i,j), takes a break, then drives the rest. For
simplicity, we model the break as occurring at the start of the arc,
so H_{jk} = t_{ij}.

#### C20. Maximum continuous driving before break

```
H_{ik} <= T_drive_max                  for all i in N, k in K
```

No driver may accumulate more than 4.5 hours of continuous driving.

#### C21. Break only on traversed arcs

```
R_{ijk} <= X_{ijk}                     for all i,j in N, k in K
```

A break can only be taken on an arc that is actually traversed.

#### C22. Time impact of breaks

Breaks add time to the route. Modify the time propagation (C14):

```
S_{ik} + s_i + t_{ij} + T_break_min * R_{ijk} - M_time * (1 - X_{ijk}) <= S_{jk}
                                       for all i,j in N, k in K, i != j
```

This replaces C14. When a break is taken (R_{ijk}=1), 45 minutes
are added to the travel time on that arc.

### 9.2 Daily Driving Limit

#### C23. Daily driving accumulation

```
W_{jk} >= W_{ik} + t_{ij} - M_drive * (1 - X_{ijk})
                                       for all i,j in N, k in K, i != j
```

W_{ik} tracks total driving time for vehicle k from the start of
the shift up to arrival at node i.

#### C24. Initial daily driving

```
W_{o_k,k} = 0                          for all k in K
```

#### C25. Standard daily driving limit

```
W_{ik} <= T_daily_drive + (T_daily_drive_ext - T_daily_drive) * E_k
                                       for all i in N, k in K
```

If E_k = 0: limit is 9h. If E_k = 1: limit is 10h.

#### C26. Extended driving limit (max 2 per week)

```
SUM_{k in K} E_k <= 2 * |DR|
```

At most 2 extensions per driver per week. If each driver drives one
vehicle, this is SUM_k E_k <= 2 per driver. For the single-day
formulation, this simplifies to limiting E_k globally.

**Note:** For a multi-day planning horizon, E_k becomes E_{k,w} per
day w, and the weekly constraint is:
```
SUM_{w in W} E_{k,w} <= 2              for all k in K
```

### 9.3 Weekly and Bi-Weekly Limits

For a single-day operational problem (the most common use case), the
weekly constraints become parameter bounds:

#### C27. Weekly driving constraint (multi-day only)

```
SUM_{w in W} W_max_{k,w} <= T_weekly_drive    for all k in K
```

where W_max_{k,w} is the total driving on day w. For single-day,
this is a post-processing check.

#### C28. Bi-weekly driving constraint (multi-day only)

```
SUM_{w=1}^{14} W_max_{k,w} <= T_biweekly_drive   for all k in K
```

### 9.4 Practical Simplification: Segment-Based Break Insertion

For tractability, we recommend modeling breaks at nodes rather than
mid-arc. See Section 13 for details.

---

## 10. Constraints: Vehicle Composition

### 10.1 Tractor Assignment

#### C29. Each used vehicle gets exactly one tractor

```
SUM_{t in TR} A^TR_{tk} = Y_k                for all k in K
```

#### C30. Each tractor assigned to at most one vehicle

```
SUM_{k in K} A^TR_{tk} <= 1                  for all t in TR
```

### 10.2 Trailer Assignment

#### C31. Each used vehicle gets exactly one trailer

```
SUM_{l in TL} A^TL_{lk} = Y_k                for all k in K
```

#### C32. Each trailer assigned to at most one vehicle

```
SUM_{k in K} A^TL_{lk} <= 1                  for all l in TL
```

### 10.3 Driver Assignment

#### C33. Each used vehicle gets exactly one driver

```
SUM_{d in DR} A^DR_{dk} = Y_k                for all k in K
```

#### C34. Each driver assigned to at most one vehicle

```
SUM_{k in K} A^DR_{dk} <= 1                  for all d in DR
```

### 10.4 Compatibility Constraints

#### C35. Tractor-trailer compatibility

```
A^TR_{tk} + A^TL_{lk} <= 1 + COMP_TR_TL_{t,l}
                                              for all t in TR, l in TL, k in K
                                              where COMP_TR_TL_{t,l} = 0
```

If tractor t and trailer l are incompatible (COMP_TR_TL_{t,l} = 0),
they cannot both be assigned to vehicle k. Equivalently, only
enumerate constraints for incompatible pairs:

```
A^TR_{tk} + A^TL_{lk} <= 1
    for all (t,l) NOT in COMP_TR_TL, for all k in K
```

#### C36. Driver-tractor compatibility

```
A^DR_{dk} + A^TR_{tk} <= 1
    for all (d,t) NOT in COMP_DR_TR, for all k in K
```

#### C37. Driver qualification for orders

If driver d is not qualified for order i, and vehicle k is assigned
driver d, then vehicle k cannot serve order i:

```
SUM_{j in N} X_{p_i,j,k} <= 1 - A^DR_{dk}
    for all i in {1..n}, d NOT in QUAL_DR_i, k in K
```

### 10.5 Capacity Linking

The vehicle capacity Q_k depends on the assigned trailer:

#### C38. Capacity determined by trailer

```
Q_k = SUM_{l in TL} cap_l * A^TL_{lk}        for all k in K
```

where cap_l is the capacity (pallets) of trailer l. Since Q_k
appears in constraint C11, this links trailer assignment to routing.

**Linearization note:** C11 becomes:
```
L_{ik} <= SUM_{l in TL} cap_l * A^TL_{lk}    for all i in C, k in K
```

This is already linear since A^TL_{lk} are binary and cap_l are constants.

---

## 11. Tachograph Modeling Approach

### 11.1 Comparison of Approaches

| Approach | Variables | Constraints | SCIP Performance | Accuracy |
|----------|-----------|-------------|------------------|----------|
| **Time-indexed** (discretize into 5-min slots) | O(K*T_slots) ~ huge | Tight LP | Good LP relaxation | Exact per slot |
| **Continuous + big-M** (our choice) | O(K*N^2) | Weak LP | Moderate, needs tuning | Exact |
| **Sequence-based** | O(K*N*B) | Moderate | Moderate | Good approx |
| **Column generation** | Exponential subproblems | Tight | Best for large | Exact |

### 11.2 Recommended Approach: Continuous-Time with Big-M

**Why this approach for SCIP:**

1. **SCIP handles big-M well** with aggressive presolve and probing.
   The key is to use tight big-M values (not naive large constants).
2. **Variable count is manageable.** We add O(|A| * |K|) binary variables
   R_{ijk} for break decisions, plus O(|N| * |K|) continuous variables
   H_{ik} and W_{ik}.
3. **No time discretization needed.** A time-indexed formulation with
   5-minute slots over a 14-hour planning horizon would create 168
   time slots per node per vehicle -- far too many.
4. **Column generation is overkill** for the target instance sizes
   (50 vehicles, 100 orders) and would require a custom branch-and-price
   implementation that the JAOT expression-based solver cannot support.

### 11.3 Tightening Big-M Constants

Critical for SCIP performance. For each big-M, compute the tightest
possible value from the data:

```python
M_time_ij = max(b_j, a_i + s_i + t_ij) - a_j   # Per-arc time big-M
M_drive = T_daily_drive_ext  # = 10.0 hours
M_load = max(Q_k for k in K)
```

Using per-arc big-M values (M_time_ij instead of a global M_time)
dramatically tightens the LP relaxation and speeds up branch-and-bound.

### 11.4 Split Break Modeling

EC 561/2006 allows splitting the 45-minute break into 15min + 30min
(in that order). To model this:

Replace binary R_{ijk} with:
- R^full_{ijk}: full 45min break on arc (i,j) by vehicle k
- R^split1_{ijk}: first 15min break on arc (i,j)
- R^split2_{ijk}: second 30min break on arc (i,j)

With constraints:
```
R^split2_{ijk} <= SUM_{(g,h) preceding (i,j) in route k} R^split1_{ghk}
```

**Recommendation:** For tractability, model only full 45-minute breaks.
Split breaks can be handled in post-processing by the dispatcher.

---

## 12. Tractability Analysis

### 12.1 Variable Count Estimate

For an instance with |K|=50 vehicles, |N_orders|=100 orders:
- Total nodes: |N| = 50 (depots) + 100 (pickups) + 100 (deliveries) + 50 (endpoints) = 300
- Arcs (sparse, not full): roughly |A| ~ 300 * 50 = 15,000 (each vehicle
  connects to a subset of relevant nodes)

| Variable Group | Formula | Count |
|----------------|---------|-------|
| X_{ijk} routing | \|A\| * \|K\| | ~750,000 (dense) |
| Z_i unserved | n | 100 |
| S_{ik} arrival time | \|N\| * \|K\| | 15,000 |
| L_{ik} load | \|C\| * \|K\| | 10,000 |
| T_i tardiness | \|C\| | 200 |
| H_{ik} segment driving | \|N\| * \|K\| | 15,000 |
| R_{ijk} break decision | \|A\| * \|K\| | ~750,000 (dense) |
| W_{ik} daily driving | \|N\| * \|K\| | 15,000 |
| E_k extended day | \|K\| | 50 |
| Y_k vehicle used | \|K\| | 50 |
| A^TR_{tk} tractor | \|TR\| * \|K\| | ~2,500 |
| A^TL_{lk} trailer | \|TL\| * \|K\| | ~2,500 |
| A^DR_{dk} driver | \|DR\| * \|K\| | ~2,500 |
| **TOTAL (dense)** | | **~1,563,000** |

### 12.2 Constraint Count Estimate

| Constraint Group | Formula | Count |
|-----------------|---------|-------|
| C1-C2 visit once | 2n | 200 |
| C3 pairing | n * \|K\| | 5,000 |
| C4 flow conservation | \|C\| * \|K\| | 10,000 |
| C5-C6 depot | 2\|K\| | 100 |
| C7 depot exclusion | 2\|K\|^2 | 5,000 |
| C8 precedence | n * \|K\| | 5,000 |
| C10 load tracking | 2\|A\| * \|K\| | ~1,500,000 |
| C11 load bounds | \|C\| * \|K\| | 10,000 |
| C14/C22 time propagation | \|A\| * \|K\| | ~750,000 |
| C16 tardiness | \|C\| * \|K\| | 10,000 |
| C18-C19 segment tracking | 2\|A\| * \|K\| | ~1,500,000 |
| C20 max driving | \|N\| * \|K\| | 15,000 |
| C21 break on arc | \|A\| * \|K\| | ~750,000 |
| C23 daily accumulation | \|A\| * \|K\| | ~750,000 |
| C25 daily limit | \|N\| * \|K\| | 15,000 |
| C29-C37 composition | ~(TR+TL+DR)*K | ~7,500 |
| **TOTAL (dense)** | | **~5,332,800** |

### 12.3 Verdict: Full Dense Formulation

**The full dense formulation with 50 vehicles and 100 orders is
NOT tractable for SCIP with a 5-minute time limit.** The 1.5M+
binary variables and 5M+ constraints will exhaust memory or fail
to find a good feasible solution.

### 12.4 Verdict: With Sparsification (Recommended)

With the simplifications in Section 13, the effective problem size drops
to approximately:

| Metric | Dense | Sparse | Reduction |
|--------|-------|--------|-----------|
| Binary variables | ~1.5M | ~80K-150K | 90-95% |
| Continuous variables | ~55K | ~25K | 55% |
| Constraints | ~5.3M | ~300K-500K | 90-94% |

**With sparsification, the problem becomes tractable for SCIP.**
Expect to find good feasible solutions (1-5% gap) within 5 minutes
for instances up to 50 vehicles / 100 orders.

---

## 13. Recommended Simplifications

### S1. Arc Sparsification (CRITICAL)

Only create variables X_{ijk} and R_{ijk} for arcs that make sense:

```python
def is_valid_arc(i, j, k):
    """Only create arc variable if this transition is plausible."""
    # No self-loops
    if i == j:
        return False
    # Vehicle k only uses its own depots
    if is_depot(i) and depot_of(i) != k:
        return False
    if is_endpoint(j) and endpoint_of(j) != k:
        return False
    # Don't go from delivery back to another delivery's pickup
    # (unless it's a different order)
    if is_delivery(i) and is_pickup(j) and order_of(i) == order_of(j):
        return False
    # Don't go from endpoint back to anywhere
    if is_endpoint(i):
        return False
    # Don't go to origin depot from anywhere
    if is_depot(j) and j != endpoint_of_depot(k):
        return False
    # Geographic filter: skip arcs where distance > threshold
    if distance(i, j) > MAX_ARC_DISTANCE:
        return False
    return True
```

**Expected reduction:** 90-95% of arcs eliminated. This is the single
most important optimization.

### S2. Vehicle-Order Compatibility Pre-filtering

Only allow vehicle k to serve order i if:
- The vehicle can reach the pickup from its depot within the time window
- The vehicle has enough capacity for the order
- The assigned driver (or any possible driver) is qualified

```python
def can_vehicle_serve_order(k, i):
    """Pre-check if vehicle k can possibly serve order i."""
    earliest_arrival = departure_time_k + t[depot_k][pickup_i]
    if earliest_arrival > b[pickup_i] + MAX_TARDINESS:
        return False
    if q[i] > max_possible_capacity_k:
        return False
    return True
```

### S3. Breaks at Nodes Only (Tachograph Simplification)

Instead of allowing breaks on arcs (R_{ijk}), only allow breaks at
customer nodes. Replace R_{ijk} with:

- B_{ik}: Binary, 1 if vehicle k takes a break at node i

**New constraints replacing C18-C22:**

```
# Segment accumulation
H_{jk} >= H_{ik} + t_{ij} - M_drive * (1 - X_{ijk})
                                   for all (i,j) in valid arcs, k in K

# Reset at break nodes
H_{ik} <= T_drive_max * (1 - B_{ik})
                                   for all i in C, k in K

# If break taken, reset and add break time
S_{jk} >= S_{ik} + s_i + T_break_min * B_{ik} + t_{ij} - M_time * (1 - X_{ijk})
                                   for all (i,j) in valid arcs, k in K

# Force break when needed (if next arc would exceed 4.5h)
H_{ik} + t_{ij} <= T_drive_max + M_drive * (1 - X_{ijk}) + M_drive * B_{ik}
                                   for all (i,j) in valid arcs, k in K
```

**Variable reduction:** From |A|*|K| binary R_{ijk} to |C|*|K| binary B_{ik}.
With 200 customer nodes and 50 vehicles: 10,000 vs 750,000.

### S4. Aggregate Vehicle Composition (If Needed)

If the problem is still too large, pre-compute valid vehicle
configurations (tractor, trailer, driver triples) and enumerate
only valid configurations:

```python
configs = []
for t in tractors:
    for l in trailers:
        if (t, l) in compatible_tr_tl:
            for d in drivers:
                if (d, t) in compatible_dr_tr:
                    configs.append((t, l, d, capacity_of(l)))
```

Replace A^TR, A^TL, A^DR with a single variable:
- V_{ck}: Binary, 1 if configuration c is used for vehicle k

This reduces the composition variables from 3*|resources|*|K| to
|configs|*|K|, and compatibility constraints become implicit.

### S5. Single-Day Planning Horizon

For the operational use case (daily dispatch), drop:
- C27 weekly driving constraint (enforce as parameter bound on daily)
- C28 bi-weekly constraint (post-processing)
- Weekly rest modeling (occurs between planning horizons)

### S6. Symmetry Breaking

If multiple vehicles share the same depot and have identical capabilities,
add ordering constraints to break symmetry:

```
Y_1 >= Y_2 >= Y_3 >= ...           (for identical vehicles at same depot)
```

And order the first customer assignment:
```
SUM_{j in C} j * X_{o_k,j,k} <= SUM_{j in C} j * X_{o_{k+1},j,k+1}
                                   for identical vehicles k, k+1
```

---

## 14. Implementation Notes for JAOT

### 14.1 Generator Class Structure

```python
class MDPDPTWTGenerator(BaseGenerator):
    """Generate MDPDP-TW-T problems.

    Multi-Depot Pickup-Delivery with Soft Time Windows,
    Tachograph constraints, and Vehicle Composition.
    """

    def generate(
        self, user_input: dict[str, Any], params: dict[str, Any]
    ) -> OptimizationProblem:
        # 1. Parse input: orders, vehicles, depots, distances, time windows
        # 2. Build valid arc set (sparsification S1)
        # 3. Build vehicle-order compatibility (S2)
        # 4. Generate variables
        # 5. Generate constraints
        # 6. Build objective expression
        # 7. Return OptimizationProblem
        ...
```

### 14.2 Expected Input Schema

```json
{
  "orders": [
    {
      "id": "order_1",
      "pickup": {"location": "A", "earliest": 8.0, "latest": 10.0, "service_time": 0.5, "pallets": 5},
      "delivery": {"location": "B", "earliest": 10.0, "latest": 14.0, "service_time": 0.5}
    }
  ],
  "depots": [
    {"id": "depot_1", "location": "X"}
  ],
  "tractors": [
    {"id": "tr_1", "depot": "depot_1", "fuel_cost_per_km": 0.35}
  ],
  "trailers": [
    {"id": "tl_1", "capacity_pallets": 33, "compatible_tractors": ["tr_1", "tr_2"]}
  ],
  "drivers": [
    {"id": "dr_1", "qualified_tractors": ["tr_1"], "qualified_orders": null}
  ],
  "distances": [
    {"from": "A", "to": "B", "km": 150, "hours": 2.0}
  ],
  "config": {
    "alpha": 1.0,
    "beta": 1000.0,
    "gamma": 5000.0,
    "max_distance_per_vehicle": 800,
    "tachograph_enabled": true,
    "time_limit_seconds": 300
  }
}
```

### 14.3 Expression Generation Strategy

The JAOT solver uses string expressions. For a problem this size,
expression strings can become very long. Recommendations:

1. **Build expressions incrementally** using list joins, not
   string concatenation.
2. **Use constraint names aggressively** for debugging.
3. **Set time_limit_seconds to 300** (5 min) as default.
4. **Set gap_tolerance to 0.02** (2%) -- for VRP, a 2% gap is
   excellent and dramatically reduces solve time vs 0.01%.
5. **Enable warm start** from a simple greedy heuristic (assign
   nearest orders to nearest vehicles).

### 14.4 Solution Interpretation

From the `OptimizationResult.solution` dict, extract routes:

```python
def extract_routes(solution: dict[str, float], vehicles, nodes):
    """Extract vehicle routes from X_{ijk} solution values."""
    routes = {}
    for k in vehicles:
        route = []
        current = depot_of(k)
        while current != endpoint_of(k):
            for j in nodes:
                var_name = f"x_{current}_{j}_{k}"
                if solution.get(var_name, 0) > 0.5:
                    route.append(j)
                    current = j
                    break
        routes[k] = route
    return routes
```

### 14.5 Phased Implementation

**Phase 1:** Core MDPDP with hard time windows (no tachograph, no composition)
- Constraints: C1-C9, C10-C13, C14-C15 (hard TW)
- Variables: X, Z, S, L
- Estimated variables: ~80K sparse, ~200K constraints

**Phase 2:** Add soft time windows
- Add: C16-C17, tardiness variables T_i, beta penalty
- Minimal additional complexity

**Phase 3:** Add tachograph (breaks-at-nodes simplified)
- Add: H, B, W, E variables and C18-C26 simplified
- Significant complexity increase

**Phase 4:** Add vehicle composition
- Add: A^TR, A^TL, A^DR, Y variables and C29-C38
- Moderate complexity increase, many constraints but mostly assignment

---

## 15. References

### Academic Papers

- Furtado, Munari et al. "Pickup and delivery problem with time windows:
  A new compact two-index formulation." Operations Research Letters, 2017.
  [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0167637717302651)

- Goel, A. "Vehicle Scheduling and Routing with Drivers' Working Hours."
  Transportation Science, 2009.
  [INFORMS](https://pubsonline.informs.org/doi/abs/10.1287/trsc.1070.0226)

- Prescott-Gagnon et al. "A metaheuristic for the time-dependent vehicle
  routing problem considering driving hours regulations."
  [ResearchGate](https://www.researchgate.net/publication/328935754)

- PDPTW-DB: "MILP-Based Offline Route Planning for PDPTW with Driver Breaks."
  ACM ICDCN 2025.
  [ACM](https://dl.acm.org/doi/10.1145/3700838.3700854)

- Bettinelli et al. "A MIP formulation for a combined vehicle routing and
  driver scheduling problem with real life constraints."
  [ResearchGate](https://www.researchgate.net/publication/281732937)

- "Vehicle routing and scheduling under hours of service regulations: A review."
  Transportation Research Part A, 2025.
  [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0965856425002939)

- Hoff et al. "A Grouping Genetic Algorithm for Multi Depot Pickup and Delivery
  Problems with Time Windows and Heterogeneous Vehicle Fleets."
  [ResearchGate](https://www.researchgate.net/publication/340534862)

- "The selective multiple depot pickup and delivery problem with multiple time
  windows and paired demand." 2025.
  [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2214716025000181)

- Derigs et al. "The multi-depot vehicle routing problem with heterogeneous
  vehicle fleet: Formulation and a variable neighborhood search implementation."
  Computers & OR, 2013.
  [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0305054813001408)

- Villegas et al. "Models and Solutions for Truck and Trailer Routing Problems."
  [ResearchGate](https://www.researchgate.net/publication/273859219)

### Regulatory Sources

- [EC Regulation 561/2006 Full Text](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:02006R0561-20200820)
- [EU Driving Time and Rest Periods Summary](https://transport.ec.europa.eu/transport-modes/road/social-provisions/driving-time-and-rest-periods_en)
- [IRU Guide to EU Drivers' Hours](https://www.iru.org/sites/default/files/2016-03/en-drivers-hours-eu.pdf)

### SCIP / Solver Resources

- [scip-routing: Exact VRPTW solver in Python](https://github.com/mmghannam/scip-routing)
- [VRPSolverEasy: Branch-Cut-and-Price for VRP](https://github.com/inria-UFF/VRPSolverEasy)
- [SCIP Parameters Reference](https://www.scipopt.org/doc/html/PARAMETERS.php)
- [Gurobi VRP FAQ](https://support.gurobi.com/hc/en-us/community/posts/7484808903825)

---

## Appendix A: Complete Constraint Summary

| # | Name | Type | Count (sparse) |
|---|------|------|----------------|
| C1 | Pickup visit | Equality | n |
| C2 | Delivery visit | Equality | n |
| C3 | Pairing | Equality | n * K |
| C4 | Flow conservation | Equality | \|C\| * K |
| C5 | Depot departure | Equality | K |
| C6 | Depot arrival | Equality | K |
| C7 | Depot exclusion | Fixed to 0 | (handled in arc filtering) |
| C8 | Precedence | Inequality | n * K |
| C9 | No self-loops | Fixed to 0 | (handled in arc filtering) |
| C10 | Load tracking | Inequality (x2) | 2 * \|A_sparse\| |
| C11 | Load bounds | Bounds | \|C\| * K |
| C12 | Initial load | Equality | K |
| C13 | Max distance | Inequality | K |
| C14/C22 | Time propagation (with breaks) | Inequality | \|A_sparse\| |
| C15 | Earliest arrival | Bounds | \|C\| * K |
| C16 | Tardiness definition | Inequality | \|C\| * K |
| C17 | Tardiness non-neg | Bounds | \|C\| |
| C18 | Segment accumulation | Inequality | \|A_sparse\| |
| C19 | Segment reset | Inequality | \|A_sparse\| |
| C20 | Max continuous driving | Bounds | \|N\| * K |
| C21 | Break on traversed arc | Inequality | \|C\| * K (breaks at nodes) |
| C23 | Daily driving accum | Inequality | \|A_sparse\| |
| C24 | Initial daily driving | Equality | K |
| C25 | Daily limit | Inequality | \|N\| * K |
| C26 | Extended driving limit | Inequality | 1 (or per driver) |
| C29 | Tractor to vehicle | Equality | K |
| C30 | Tractor uniqueness | Inequality | \|TR\| |
| C31 | Trailer to vehicle | Equality | K |
| C32 | Trailer uniqueness | Inequality | \|TL\| |
| C33 | Driver to vehicle | Equality | K |
| C34 | Driver uniqueness | Inequality | \|DR\| |
| C35 | Tractor-trailer compat | Inequality | incompatible pairs * K |
| C36 | Driver-tractor compat | Inequality | incompatible pairs * K |
| C37 | Driver qualification | Inequality | unqualified combos |
| C38 | Capacity linking | Inequality | \|C\| * K |

---

## Appendix B: SCIP Tuning Recommendations

```python
# Recommended SCIP parameters for this formulation
solver_options = {
    "time_limit_seconds": 300,      # 5 minutes
    "gap_tolerance": 0.02,          # 2% gap is excellent for VRP
}

# Additional SCIP params to set via PySCIPOpt:
# model.setParam("presolving/maxrounds", 10)         # Aggressive presolve
# model.setParam("separating/maxrounds", 5)          # More cutting planes
# model.setParam("heuristics/rens/freq", 10)         # RENS heuristic
# model.setParam("heuristics/rins/freq", 10)         # RINS heuristic
# model.setParam("branching/relpscost/priority", 10) # Reliable pseudocost
# model.setParam("conflict/enable", True)            # Conflict analysis
```

---

## Appendix C: Warm Start Heuristic (Greedy)

A critical SCIP performance booster: provide an initial feasible solution.

```
Algorithm: Greedy Construction Heuristic
1. Sort orders by pickup earliest time
2. For each order (in sorted order):
   a. For each vehicle (sorted by proximity to pickup):
      - Check: can vehicle reach pickup within time window?
      - Check: does vehicle have capacity?
      - Check: would this violate tachograph? (simple check: total hours < 9)
      - If all pass: assign order to vehicle, update route
   b. If no vehicle can serve: mark Z_i = 1 (unserved)
3. Output: X_{ijk}, S_{ik}, L_{ik} values as warm start
```

This heuristic typically produces solutions within 20-40% of optimal,
giving SCIP an excellent starting point for branch-and-bound.
