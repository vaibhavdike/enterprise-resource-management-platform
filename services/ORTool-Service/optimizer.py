# ============================================================
# optimizer.py
# Intelligent Resource Allocation using Google OR-Tools
#
# UPDATED (this revision): A project (OPPORTUNITY_ID + SKILL_ID)
# can now be staffed by MULTIPLE employees simultaneously.
#
#   Phase 1 -> Full-Time employees (160h/month, available every
#              required month) are preferred and allocated first.
#   Phase 2 -> Partial employees (80h/month, available every
#              required month) fill whatever demand remains.
#   No Phase 3 -> employees available for only SOME months of a
#              project are still fully excluded (unchanged rule).
#
# Every section that was changed is marked with:
#   # ==== MODIFIED: <reason> ====
# Everything else (Snowflake connection, data loading, input
# views, output table/schema, capacity normalization, general
# project structure) is preserved as-is.
# ============================================================
import os
from snowflake.snowpark import Session
from ortools.linear_solver import pywraplp
import math
import pandas as pd

# ============================================================
# 1. Snowflake Connection
# ============================================================


# for local development

# connection_parameters = {
#     "account": "A4357138117071-ACCELIRATE_PARTNER",
#     "user": "VAIBHAVDIKE",
#     "password": "Vaibhav@123456789",
#     "role": "SYSADMIN",
#     "warehouse": "DEMO_WH",
#     "database": "IRM_DB",
#     "schema": "OPERATIONAL"
# }

# session = Session.builder.configs(connection_parameters).create()



# for production

import os


connection_params = {
    "host": os.environ["SNOWFLAKE_HOST"],
    "account": os.environ["SNOWFLAKE_ACCOUNT"],
    "authenticator": "oauth",
    "token": open("/snowflake/session/token").read().strip(),
    "warehouse": "DEMO_WH",
    "database": "IRM_DB",
    "schema": "OPERATIONAL"
}

session = Session.builder.configs(connection_params).create()

print("=" * 70)
print("Connected to Snowflake Successfully")
print("=" * 70)

# ============================================================
# 2. Load Views from snowflake
# ============================================================

print("\nLoading Supply View...")

supply_df = (
    session
    .table("IRM_DB.OPERATIONAL.V_OPT_SUPPLY")
    .to_pandas()
)


print(f"Supply Rows : {len(supply_df)}")

print("\nLoading Demand View...")

demand_df = (
    session
    .table("IRM_DB.OPERATIONAL.VW_OPT_DEMAND")
    .to_pandas()
)

print(f"Demand Rows : {len(demand_df)}")

print("\nLoading Eligibility View...")

eligibility_df = (
    session
    .table("IRM_DB.OPERATIONAL.V_OPT_ELIGIBILITY")
    .to_pandas()
)

print(f"Eligibility Rows : {len(eligibility_df)}")

# ============================================================
# 3. Preview Data
# ============================================================

print("\n")
print("=" * 70)
print("SUPPLY")
print("=" * 70)

print(supply_df.head())

print("\nColumns")
print(supply_df.columns.tolist())

print("\n")
print("=" * 70)
print("DEMAND")
print("=" * 70)

print(demand_df.head())

print("\nColumns")
print(demand_df.columns.tolist())

print("\n")
print("=" * 70)
print("ELIGIBILITY")
print("=" * 70)

print(eligibility_df.head())

print("\nColumns")
print(eligibility_df.columns.tolist())

# ============================================================
# 4. Create OR-Tools Solver
# ============================================================

print("\nCreating SCIP Solver...")

solver = pywraplp.Solver.CreateSolver("SCIP")

if solver is None:
    raise Exception("Failed to create SCIP Solver")

print("SCIP Solver Created Successfully")

# ============================================================
# 5. Create Eligibility Lookup
# ============================================================

print("\nBuilding Eligibility Lookup...")

eligible_lookup = set()

for _, row in eligibility_df.iterrows():

    eligible_lookup.add(
        (
            row["EMPLOYEE_ID"],
            row["SKILL_ID"]
        )
    )

print(f"Eligible Combinations : {len(eligible_lookup)}")

# ============================================================
# Capacity Classification Helper (UNCHANGED)
# ============================================================
#
#   Capacity >= 145         -> FULL_TIME  -> normalized to 160
#   80 <= Capacity < 145    -> PARTIAL    -> normalized to 80
#   Capacity < 80           -> UNAVAILABLE -> normalized to 0
#
# The optimizer uses these normalized values everywhere instead
# of the raw CAPACITY_HOURS value.
# ============================================================

def classify_capacity(capacity_hours):

    capacity_hours = float(capacity_hours)

    if capacity_hours >= 145:
        return "FULL_TIME", 160.0
    elif capacity_hours >= 80:
        return "PARTIAL", 80.0
    else:
        return "UNAVAILABLE", 0.0


# ============================================================
# ==== MODIFIED: Priority weighting for Phase 1 vs Phase 2 ====
# A large constant added to every FULL_TIME candidate's score.
# This is what forces the solver to always prefer consuming a
# project's demand budget with Full-Time employees before it
# ever "spends" that budget on Partial employees. It is set far
# larger than the maximum possible spread of the existing score
# components (availability_bonus <= 1000, proficiency*100 <= a
# few hundred, is_primary*50, cost_rate*0.10 small), so no
# combination of Partial employees can ever outscore a Full-Time
# employee for the same demand row.
# ============================================================

FULL_TIME_PRIORITY_BONUS = 1_000_000.0

# ============================================================
# Normalized Employee Capacity Lookup (Employee + Month) (UNCHANGED)
# ============================================================

print("\nBuilding Normalized Employee Capacity Lookup...")

employee_month_capacity = {}   # (EMPLOYEE_ID, PERIOD_MONTH) -> (TYPE, EFFECTIVE_CAPACITY)

employee_capacity_raw = (
    supply_df
    .groupby(["EMPLOYEE_ID", "PERIOD_MONTH"])["CAPACITY_HOURS"]
    .first()
    .reset_index()
)

for _, row in employee_capacity_raw.iterrows():

    cap_type, eff_cap = classify_capacity(row["CAPACITY_HOURS"])

    employee_month_capacity[
        (row["EMPLOYEE_ID"], row["PERIOD_MONTH"])
    ] = (cap_type, eff_cap)

print(f"Employee-Month Capacity Records : {len(employee_month_capacity)}")

# ============================================================
# Supply Lookup (Employee + Skill + Month) (UNCHANGED)
# ============================================================

print("\nBuilding Supply Lookup...")

supply_lookup = {}

for _, row in supply_df.iterrows():

    key = (row["EMPLOYEE_ID"], row["SKILL_ID"], row["PERIOD_MONTH"])
    supply_lookup[key] = row

print(f"Supply Lookup Records : {len(supply_lookup)}")

# ============================================================
# Build Project Definitions (OPPORTUNITY_ID + SKILL_ID) (UNCHANGED)
# ============================================================

print("\nBuilding Project Definitions...")

projects = {}   # (OPPORTUNITY_ID, SKILL_ID) -> list of demand rows

for _, demand in demand_df.iterrows():

    project_key = (demand["OPPORTUNITY_ID"], demand["SKILL_ID"])

    projects.setdefault(project_key, []).append(demand)

print(f"Total Projects Identified : {len(projects)}")

# ============================================================
# ==== MODIFIED: Required FTE (informational / logging only) ====
# Required FTE = CEILING(Total Project Demand Hours / 160).
# This number is NOT used as a hard constraint anywhere - the
# demand constraints (per month, further below) already cap how
# many hours can be consumed, which is what actually limits how
# many employees get assigned. This block exists purely so the
# console output / your team can see intended staffing size vs.
# what was actually achievable given supply.
# ============================================================

print("\nCalculating Required FTE per Project (informational)...")

project_required_fte = {}

for project_key, demand_rows in projects.items():

    total_demand_hours = sum(float(d["DEMAND_HOURS"]) for d in demand_rows)

    required_fte = math.ceil(total_demand_hours / 160.0) if total_demand_hours > 0 else 0

    project_required_fte[project_key] = {
        "total_demand_hours": total_demand_hours,
        "required_fte": required_fte
    }

print(f"Required FTE Calculated For : {len(project_required_fte)} projects")

# ============================================================
# ==== MODIFIED: Project-Level Eligibility (BOTH tiers kept) ====
# Previously, if ANY Full-Time candidate existed for a project,
# Partial candidates were discarded entirely (elif branch), which
# meant a project could only ever be staffed by one tier.
#
# Now BOTH pools (full_time candidates AND partial candidates)
# are retained for every project. This is what allows Phase 2
# (Partial) to top up a project after Phase 1 (Full-Time) has
# used up all available Full-Time employees.
#
# The full-duration eligibility rule is otherwise UNCHANGED:
#   - Employee must be eligible for the skill.
#   - Employee must have a supply row for EVERY required month.
#   - If ANY required month is UNAVAILABLE (or missing), the
#     employee is disqualified entirely (still no Phase 3 /
#     partial-duration fallback).
#   - Employee's tier for the project = worst monthly tier seen
#     (FULL_TIME only if every month is FULL_TIME, otherwise
#     PARTIAL as long as no month is UNAVAILABLE).
# ============================================================

print("\nEvaluating Project-Level Employee Eligibility...")

project_eligible_employees = {}
# project_key -> {
#     "full_time": { employee_id: {"months": {...}, "score": ...} },
#     "partial":   { employee_id: {"months": {...}, "score": ...} }
# }

all_employee_ids = supply_df["EMPLOYEE_ID"].unique()

for project_key, demand_rows in projects.items():

    opportunity_id, skill_id = project_key

    fte_candidates = {}
    partial_candidates = {}

    for employee_id in all_employee_ids:

        # Employee must be eligible for this skill at all
        if (employee_id, skill_id) not in eligible_lookup:
            continue

        months_ok = True
        worst_tier = "FULL_TIME"   # downgraded to PARTIAL if any month requires it
        month_hours = {}
        total_score = 0.0

        for demand in demand_rows:

            period_month = demand["PERIOD_MONTH"]

            supply_key = (employee_id, skill_id, period_month)

            if supply_key not in supply_lookup:
                months_ok = False
                break

            supply_row = supply_lookup[supply_key]

            cap_type, eff_cap = employee_month_capacity.get(
                (employee_id, period_month),
                ("UNAVAILABLE", 0.0)
            )

            if cap_type == "UNAVAILABLE":
                months_ok = False
                break

            if cap_type == "PARTIAL":
                worst_tier = "PARTIAL"

            demand_hours = float(demand["DEMAND_HOURS"])
            effective_hours = min(demand_hours, eff_cap)

            month_hours[period_month] = effective_hours

            proficiency = float(supply_row["PROFICIENCY"])
            is_primary = 1 if supply_row["IS_PRIMARY"] else 0
            cost_rate = float(supply_row["COST_RATE_HOURLY"])

            if eff_cap >= 160:
                availability_bonus = 1000
            elif eff_cap >= 120:
                availability_bonus = 500
            elif eff_cap >= 80:
                availability_bonus = 200
            else:
                availability_bonus = 0

            total_score += (
                availability_bonus
                + proficiency * 100
                + is_primary * 50
                - cost_rate * 0.10
            )

        if not months_ok:
            continue

        # ==== MODIFIED: apply the Phase-1 priority bonus here ====
        if worst_tier == "FULL_TIME":
            total_score += FULL_TIME_PRIORITY_BONUS

        candidate_info = {
            "months": month_hours,
            "score": total_score,
            "tier": worst_tier   # ==== MODIFIED: tier now stored on the candidate ====
        }

        if worst_tier == "FULL_TIME":
            fte_candidates[employee_id] = candidate_info
        else:
            partial_candidates[employee_id] = candidate_info

    # ==== MODIFIED: both tiers stored, no elif/exclusivity ====
    project_eligible_employees[project_key] = {
        "full_time": fte_candidates,
        "partial": partial_candidates
    }

eligible_project_count = sum(
    1 for v in project_eligible_employees.values()
    if v["full_time"] or v["partial"]
)

print(f"Projects With Eligible Employees : {eligible_project_count} / {len(projects)}")

# ==== MODIFIED: informational summary of Phase 1 / Phase 2 pool sizes ====
print("\nProject Staffing Pool Summary (informational):")
for project_key, info in project_eligible_employees.items():
    req = project_required_fte[project_key]
    print(
        f"  {project_key} | Required FTE: {req['required_fte']} "
        f"(Total Demand: {req['total_demand_hours']}h) | "
        f"Full-Time Available: {len(info['full_time'])} | "
        f"Partial Available: {len(info['partial'])}"
    )

# ============================================================
# ==== MODIFIED: Decision Variable Creation (multi-employee) ====
# One BINARY variable per (employee, project), same as before,
# EXCEPT variables are now created for BOTH the full_time pool
# AND the partial pool of a project (not just one exclusive
# tier). Multiple employees can therefore be selected for the
# same project at once.
# ============================================================

print("\nCreating Decision Variables (Project-Level, Multi-Employee)...")

decision_variables = {}
# (employee_id, project_key) -> solver BoolVar

variable_metadata = {}
# (employee_id, project_key) -> {"months": {...}, "score": ..., "tier": ...}

for project_key, info in project_eligible_employees.items():

    # ==== MODIFIED: loop over both tiers instead of a single dict ====
    for tier_name, tier_pool in (("FULL_TIME", info["full_time"]), ("PARTIAL", info["partial"])):

        for employee_id, candidate_info in tier_pool.items():

            variable_name = (
                f"y_{employee_id}_"
                f"{project_key[0]}_{project_key[1]}_{tier_name}"
            )

            var = solver.BoolVar(variable_name)

            decision_variables[(employee_id, project_key)] = var
            variable_metadata[(employee_id, project_key)] = candidate_info

print(f"Decision Variables Created : {len(decision_variables)}")

# ============================================================
# 7. Display Sample Variables
# ============================================================

print("\nSample Decision Variables")

count = 0

for key in decision_variables.keys():

    print(key)

    count += 1

    if count == 10:
        break

print("\nOptimizer Initialization Complete.")

# ============================================================
# ==== MODIFIED: Project Uniqueness Constraint REMOVED ====
# The old "at most one employee per project" constraint is no
# longer valid, since a project may now legitimately require
# several Full-Time and/or Partial employees simultaneously
# (e.g. 2 Full-Time + 3 Partial on the same project/month).
#
# No replacement upper-bound constraint on employee COUNT per
# project is added, because the Demand Constraint (below) already
# caps the total HOURS a project can absorb per month. Since each
# employee variable contributes a fixed, capped number of hours,
# the demand constraint is what naturally limits how many
# employees can usefully be assigned - exactly matching "allocate
# as many employees as needed, but never more than demand
# requires."
# ============================================================

print("\nProject Uniqueness Constraint skipped (multi-employee projects are now allowed).")

# ============================================================
# Employee Capacity Constraints (UNCHANGED)
# ============================================================
# Uses the normalized effective capacity (160 / 80 / 0) for each
# employee + month. An employee can appear across multiple
# projects/months; this constraint still sums every project
# variable that touches a given employee-month against that
# employee's normalized capacity for that month, so employees can
# never be over-allocated across projects.
# ============================================================

print("\nAdding Employee Capacity Constraints...")

capacity_constraints = 0

for (employee_id, period_month), (cap_type, eff_cap) in employee_month_capacity.items():

    constraint = solver.Constraint(
        0,
        eff_cap,
        f"Capacity_{employee_id}_{period_month}"
    )

    for (emp_id, project_key), var in decision_variables.items():

        if emp_id != employee_id:
            continue

        meta = variable_metadata[(emp_id, project_key)]

        if period_month in meta["months"]:
            constraint.SetCoefficient(var, meta["months"][period_month])

    capacity_constraints += 1

print(f"Capacity Constraints Added : {capacity_constraints}")

# ============================================================
# Demand Constraints (UNCHANGED logic - now naturally multi-employee)
# ============================================================
# Each demand row (one month of one project) is still capped at
# its DEMAND_HOURS. Because multiple (employee, project) variables
# can now share the same project_key, this loop already sums
# contributions from EVERY eligible employee (Full-Time or
# Partial) touching that month - this is exactly what allows
# several employees to jointly satisfy one demand row, with the
# total never exceeding DEMAND_HOURS.
# ============================================================

print("\nAdding Demand Constraints...")

demand_constraints = 0

demand_index = {}
# DEMAND_ID -> (project_key, period_month, demand_hours)

for project_key, demand_rows in projects.items():
    for demand in demand_rows:
        demand_index[demand["DEMAND_ID"]] = (
            project_key,
            demand["PERIOD_MONTH"],
            float(demand["DEMAND_HOURS"])
        )

for demand_id, (project_key, period_month, required_hours) in demand_index.items():

    constraint = solver.Constraint(
        0,
        required_hours,
        f"Demand_{demand_id}"
    )

    for (employee_id, p_key), var in decision_variables.items():

        if p_key != project_key:
            continue

        meta = variable_metadata[(employee_id, p_key)]

        if period_month in meta["months"]:
            constraint.SetCoefficient(var, meta["months"][period_month])

    demand_constraints += 1

print(f"Demand Constraints Added : {demand_constraints}")

# ============================================================
# Objective Function (UNCHANGED mechanism)
# ============================================================
# Same scoring inputs as before (proficiency, primary skill, cost
# rate, availability bonus), now with the Full-Time priority
# bonus baked into each candidate's score (see modification above).
# Because the objective is a straight sum of positive-value
# variables constrained only by capacity and demand, maximizing it
# automatically:
#   1) Uses Full-Time employees first wherever a project's demand
#      budget allows (their score dominates any Partial mix).
#   2) Still uses Partial employees to fill whatever demand budget
#      is left over once Full-Time supply is exhausted.
#   3) Never leaves usable capacity unassigned, since every
#      additional valid assignment only adds to the objective.
# ============================================================

print("\nBuilding Objective Function...")

objective = solver.Objective()

for (employee_id, project_key), var in decision_variables.items():

    meta = variable_metadata[(employee_id, project_key)]

    objective.SetCoefficient(var, meta["score"])

objective.SetMaximization()

print("Objective Function Created Successfully.")

# ============================================================
# 11. Solve Optimization Model
# ============================================================

print("\nSolving Optimization Model...")

status = solver.Solve()

if status == pywraplp.Solver.OPTIMAL:
    print("Optimal Solution Found")

elif status == pywraplp.Solver.FEASIBLE:
    print("Feasible Solution Found")

elif status == pywraplp.Solver.INFEASIBLE:
    print("Model is Infeasible")
    exit()

elif status == pywraplp.Solver.UNBOUNDED:
    print("Model is Unbounded")
    exit()

else:
    print("No Solution Found")
    exit()

print(f"\nObjective Value : {solver.Objective().Value():,.2f}")

# ============================================================
# Extract Solution (UNCHANGED extraction logic)
# ============================================================
# This loop already iterates over EVERY (employee, project)
# decision variable independently, so it required NO changes to
# support multiple employees per project - each selected employee
# simply produces its own set of monthly allocation rows, all
# sharing the same OPPORTUNITY_ID/SKILL_ID/DEMAND_ID.
# ============================================================

print("\nExtracting Solution...")

allocation_results = []

for (employee_id, project_key), var in decision_variables.items():

    if var.solution_value() < 0.5:
        continue

    opportunity_id, skill_id = project_key

    meta = variable_metadata[(employee_id, project_key)]

    for demand in projects[project_key]:

        period_month = demand["PERIOD_MONTH"]
        demand_id = demand["DEMAND_ID"]

        assigned_hours = meta["months"].get(period_month, 0.0)

        if assigned_hours <= 0.001:
            continue

        supply_row = supply_lookup[(employee_id, skill_id, period_month)]

        allocation_results.append({

            "EMPLOYEE_ID": employee_id,

            "DEMAND_ID": demand_id,

            "OPPORTUNITY_ID": demand["OPPORTUNITY_ID"],

            "BUSINESS_UNIT": demand["BUSINESS_UNIT"],

            "SKILL_ID": demand["SKILL_ID"],

            "PERIOD_MONTH": period_month,

            "DEMAND_HOURS": demand["DEMAND_HOURS"],

            "ASSIGNED_HOURS": round(assigned_hours, 2),

            "PROFICIENCY": supply_row["PROFICIENCY"],

            "IS_PRIMARY": supply_row["IS_PRIMARY"],

            "COST_RATE_HOURLY": supply_row["COST_RATE_HOURLY"]

          })

# ------------------------------------------------------------
# FIX (kept from prior version): Always construct allocation_df
# with the full expected column list, so an empty result set
# still has the right schema for downstream code.
# ------------------------------------------------------------
allocation_columns = [
    "EMPLOYEE_ID",
    "DEMAND_ID",
    "OPPORTUNITY_ID",
    "BUSINESS_UNIT",
    "SKILL_ID",
    "PERIOD_MONTH",
    "DEMAND_HOURS",
    "ASSIGNED_HOURS",
    "PROFICIENCY",
    "IS_PRIMARY",
    "COST_RATE_HOURLY"
]

allocation_df = pd.DataFrame(allocation_results, columns=allocation_columns)

print(f"\nAssignments Created : {len(allocation_df)}")

print("\nSample Allocation")

print(allocation_df.head(10))

# ============================================================
# 13. Write Results to Snowflake (UNCHANGED)
# ============================================================

from datetime import datetime
import pandas as pd

if allocation_df.empty:

    print("\n" + "=" * 70)
    print("No Assignments Were Made - Skipping Snowflake Write")
    print("=" * 70)
    print(
        "No employee passed project-level eligibility for any project. "
        "Check Supply/Demand month coverage and eligibility data."
    )

else:

    print("\nWriting Allocation Plan to Snowflake...")

    # ------------------------------------------------------------
    # Add Run Timestamp
    # ------------------------------------------------------------
    allocation_df["RUN_TS"] = pd.Timestamp.now()

    # ------------------------------------------------------------
    # Convert datatypes
    # ------------------------------------------------------------
    allocation_df["PERIOD_MONTH"] = pd.to_datetime(allocation_df["PERIOD_MONTH"])

    print("\nAllocation DataFrame Columns:")
    print(allocation_df.columns.tolist())

    print("\nSample Allocation DataFrame:")
    print(allocation_df.head())

    allocation_df["DEMAND_HOURS"] = allocation_df["DEMAND_HOURS"].astype(float)
    allocation_df["ASSIGNED_HOURS"] = allocation_df["ASSIGNED_HOURS"].astype(float)
    allocation_df["COST_RATE_HOURLY"] = allocation_df["COST_RATE_HOURLY"].astype(float)
    allocation_df["PROFICIENCY"] = allocation_df["PROFICIENCY"].astype(int)
    allocation_df["IS_PRIMARY"] = allocation_df["IS_PRIMARY"].astype(bool)
    # ------------------------------------------------------------
    # Arrange Columns
    # ------------------------------------------------------------
    allocation_df = allocation_df[
        [
            "RUN_TS",
            "EMPLOYEE_ID",
            "DEMAND_ID",
            "OPPORTUNITY_ID",
            "BUSINESS_UNIT",
            "SKILL_ID",
            "PERIOD_MONTH",
            "DEMAND_HOURS",
            "ASSIGNED_HOURS",
            "PROFICIENCY",
            "IS_PRIMARY",
            "COST_RATE_HOURLY"
        ]]
    print("\nData Types")
    print(allocation_df.dtypes)

    # ------------------------------------------------------------
    # Create Snowpark DataFrame
    # ------------------------------------------------------------
    snow_df = session.create_dataframe(allocation_df)

    # ------------------------------------------------------------
    # Save to Snowflake
    # ------------------------------------------------------------
    snow_df.write.mode("overwrite").save_as_table(
        "IRM_DB.OPERATIONAL.OPTIMIZER_ALLOCATION_PLAN"
    )

    print("=" * 70)
    print("Allocation Plan Successfully Written to Snowflake")
    print("=" * 70)

    print(f"Rows Written : {len(allocation_df)}")