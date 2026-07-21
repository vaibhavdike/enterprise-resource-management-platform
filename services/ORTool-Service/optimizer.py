# ============================================================
# optimizer.py
# Intelligent Resource Allocation POC
#
# UPDATED (this revision):
#
#   1. SCHEMA MIGRATION
#      - Supply view    : IRM_DB.OPERATIONAL.V_OPT_SUPPLY
#      - Demand view     : IRM_DB.OPERATIONAL.VIEW_OPT_DEMAND
#      - Eligibility view: IRM_DB.OPERATIONAL.V_OPT_ELIGIBILITY
#      - BUSINESS_UNIT removed everywhere (no longer exists upstream)
#      - AVAILABILITY_HOURS arrives already normalized (160/80/0),
#        so the old threshold-based classify_capacity() was replaced
#        with a direct mapping. No re-normalization is performed.
#
#   2. ENHANCEMENT 1 - Primary Skill Priority Across All Skills
#      Employees are now scored so that:
#          Full-Time + Primary  >  Partial + Primary
#              >  Full-Time + Secondary  >  Partial + Secondary
#      This is achieved purely through candidate scoring + the
#      existing shared employee-capacity constraint. Still ONE
#      OR-Tools model, ONE solve, ONE objective - no second pass.
#
#   3. ENHANCEMENT 2 - Enterprise Explainability
#      New, separate outputs only (existing allocation output is
#      unchanged): explainability_selected_df, explainability_rejected_df,
#      project_summary_df, overall_summary_df.
#
# Every changed/added section is marked with:
#   # ==== MODIFIED: <reason> ====   (existing logic altered)
#   # ==== NEW: <reason> ====        (net-new logic, Enhancement 2)
#
# Preserved as-is: Snowflake connection mechanism, OR-Tools model
# type (SCIP), multi-employee-per-project capability, demand/
# capacity constraint mechanism, existing allocation_df output
# and its write to OPTIMIZER_ALLOCATION_PLAN.
# ============================================================
import os
from snowflake.snowpark import Session
from ortools.linear_solver import pywraplp
import math
import pandas as pd
from datetime import datetime

# ============================================================
# 1. Snowflake Connection (UNCHANGED)
# ============================================================

# for local development

# connection_parameters = {
#     "account": "A4357138117071-ACCELIRATE_PARTNER",
#     "user": "VAIBHAVDIKE",
#     "password": "Vaibhav@123456789",
#     "role": "SYSADMIN",
#     "warehouse": "DEMO_WH",
#     "database": "IRM_DATABASE",
#     "schema": "OPERATIONAL"
# }

# session = Session.builder.configs(connection_parameters).create()


# credentials for production

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
# 2. Load Views from Snowflake
# ==== MODIFIED: new view names, new demand schema (no BUSINESS_UNIT) ====
# ============================================================

print("\nLoading Supply View...")

supply_df = (
    session
    .table("IRM_DATABASE.OPERATIONAL.V_OPT_SUPPLY")
    .to_pandas()
)

print(f"Supply Rows : {len(supply_df)}")

print("\nLoading Demand View...")

# ==== MODIFIED: view renamed VW_OPT_DEMAND -> VIEW_OPT_DEMAND ====
demand_df = (
    session
    .table("IRM_DATABASE.OPERATIONAL.VIEW_OPT_DEMAND")
    .to_pandas()
)

print(f"Demand Rows : {len(demand_df)}")

print("\nLoading Eligibility View...")

eligibility_df = (
    session
    .table("IRM_DATABASE.OPERATIONAL.V_OPT_ELIGIBILITY")
    .to_pandas()
)

print(f"Eligibility Rows : {len(eligibility_df)}")

# ============================================================
# 3. Preview Data (UNCHANGED)
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
# 4. Create OR-Tools Solver (UNCHANGED)
# ============================================================

print("\nCreating SCIP Solver...")

solver = pywraplp.Solver.CreateSolver("SCIP")

if solver is None:
    raise Exception("Failed to create SCIP Solver")

print("SCIP Solver Created Successfully")

# ============================================================
# 5. Create Eligibility Lookup
# ==== MODIFIED: also keep a details dict (IS_PRIMARY, PROFICIENCY,
# COST_RATE_HOURLY per employee/skill) for scoring + explainability.
# BUSINESS_UNIT was never part of eligibility, so no removal needed here.
# ============================================================

print("\nBuilding Eligibility Lookup...")

eligible_lookup = set()
eligibility_details = {}   # (EMPLOYEE_ID, SKILL_ID) -> {"IS_PRIMARY":..., "PROFICIENCY":..., "COST_RATE_HOURLY":...}

for _, row in eligibility_df.iterrows():

    key = (row["EMPLOYEE_ID"], row["SKILL_ID"])

    eligible_lookup.add(key)

    eligibility_details[key] = {
        "IS_PRIMARY": bool(row["IS_PRIMARY"]),
        "PROFICIENCY": float(row["PROFICIENCY"]),
        "COST_RATE_HOURLY": float(row["COST_RATE_HOURLY"])
    }

print(f"Eligible Combinations : {len(eligible_lookup)}")

# ============================================================
# Capacity Classification Helper
# ==== MODIFIED: AVAILABILITY_HOURS is already normalized upstream
# (160 = Full-Time, 80 = Partial, 0 = Not Available). The previous
# threshold logic (>=145, >=80) has been removed - we now map the
# incoming value directly instead of re-normalizing it in Python.
# ============================================================

def classify_availability(availability_hours):

    availability_hours = float(availability_hours)

    if availability_hours >= 160:
        return "FULL_TIME", 160.0
    elif availability_hours >= 80:
        return "PARTIAL", 80.0
    else:
        return "UNAVAILABLE", 0.0


# ============================================================
# Priority Weighting Constants
# ==== MODIFIED: Changed priority hierarchy ====
# Required business hierarchy (per this revision):
#     1. Full-Time + Primary   (FULL_TIME_BONUS + PRIMARY_BONUS)
#     2. Full-Time + Secondary (FULL_TIME_BONUS only)
#     3. Partial   + Primary   (PRIMARY_BONUS only)
#     4. Partial   + Secondary (neither bonus)
#
# This is the OPPOSITE ranking of the previous revision (which put
# Partial+Primary ahead of Full-Time+Secondary). To flip the ranking
# we only need to flip which Big-M constant is larger:
#   - FULL_TIME_PRIORITY_BONUS is now the LARGER constant, so
#     employment-type (Full-Time vs Partial) dominates skill-type
#     (Primary vs Secondary) whenever the two disagree.
#   - PRIMARY_SKILL_PRIORITY_BONUS remains the tie-breaker *within*
#     the same employment-type tier (Primary still beats Secondary
#     among Full-Time employees, and still beats Secondary among
#     Partial employees).
# Both constants remain far larger than the natural spread of the
# base score components (availability_bonus <= 100000/month,
# proficiency*20, cost_rate*0.10), so tier ordering can never be
# reversed by them, and the required "never pick Partial while an
# eligible Full-Time employee still exists" rule falls out naturally
# of the solver maximizing total score under the existing capacity/
# demand constraints - no additional constraint was needed.
#
# No other logic changes: still ONE OR-Tools model, ONE solve, ONE
# objective, and the same four candidate pools / decision variables
# as before.
# ============================================================

FULL_TIME_PRIORITY_BONUS = 10_000_000.0
PRIMARY_SKILL_PRIORITY_BONUS = 1_000_000.0

# ============================================================
# Normalized Employee Capacity Lookup (Employee + Month)
# ==== MODIFIED: source column CAPACITY_HOURS -> AVAILABILITY_HOURS ====
# ============================================================

print("\nBuilding Normalized Employee Capacity Lookup...")

employee_month_capacity = {}   # (EMPLOYEE_ID, PERIOD_MONTH) -> (TYPE, EFFECTIVE_CAPACITY)

employee_capacity_raw = (
    supply_df
    .groupby(["EMPLOYEE_ID", "PERIOD_MONTH"])["AVAILABILITY_HOURS"]
    .first()
    .reset_index()
)

for _, row in employee_capacity_raw.iterrows():

    cap_type, eff_cap = classify_availability(row["AVAILABILITY_HOURS"])

    employee_month_capacity[
        (row["EMPLOYEE_ID"], row["PERIOD_MONTH"])
    ] = (cap_type, eff_cap)

print(f"Employee-Month Capacity Records : {len(employee_month_capacity)}")

# ============================================================
# Supply Lookup (Employee + Skill + Month) (UNCHANGED mechanism)
# ============================================================

print("\nBuilding Supply Lookup...")

supply_lookup = {}

for _, row in supply_df.iterrows():

    key = (row["EMPLOYEE_ID"], row["SKILL_ID"], row["PERIOD_MONTH"])
    supply_lookup[key] = row

print(f"Supply Lookup Records : {len(supply_lookup)}")

# ============================================================
# Build Project Definitions (OPPORTUNITY_ID + SKILL_ID)
# ==== MODIFIED: no BUSINESS_UNIT in demand rows anymore ====
# ============================================================

print("\nBuilding Project Definitions...")

projects = {}   # (OPPORTUNITY_ID, SKILL_ID) -> list of demand rows

for _, demand in demand_df.iterrows():

    project_key = (demand["OPPORTUNITY_ID"], demand["SKILL_ID"])

    projects.setdefault(project_key, []).append(demand)

print(f"Total Projects Identified : {len(projects)}")

# ============================================================
# Required FTE (informational / logging only) (UNCHANGED)
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
# Project-Level Eligibility - FOUR TIERS
# ==== MODIFIED: candidates are now split into four pools instead of
# two (FULL_TIME / PARTIAL). Primary/Secondary status is read once
# from the eligibility view per (EMPLOYEE_ID, SKILL_ID) - it is a
# property of the employee-skill relationship, not something that
# should be recomputed per month. The old per-month `is_primary * 50`
# score term is removed (it is now handled once, globally, via
# PRIMARY_SKILL_PRIORITY_BONUS below - keeping both would double count).
#
# Full-duration eligibility rule is otherwise UNCHANGED:
#   - Employee must be eligible for the skill.
#   - Employee must have a supply row for EVERY required month.
#   - If ANY required month is UNAVAILABLE (or missing), the employee
#     is disqualified entirely (still no partial-duration fallback).
#   - Employee's FT/Partial tier for the project = worst monthly tier
#     seen (FULL_TIME only if every month is FULL_TIME, otherwise
#     PARTIAL as long as no month is UNAVAILABLE).
# ============================================================

print("\nEvaluating Project-Level Employee Eligibility...")

project_eligible_employees = {}
# project_key -> {
#     "FULL_TIME_PRIMARY":   { employee_id: candidate_info },
#     "PARTIAL_PRIMARY":     { employee_id: candidate_info },
#     "FULL_TIME_SECONDARY": { employee_id: candidate_info },
#     "PARTIAL_SECONDARY":   { employee_id: candidate_info },
# }

TIER_NAMES = ["FULL_TIME_PRIMARY", "PARTIAL_PRIMARY", "FULL_TIME_SECONDARY", "PARTIAL_SECONDARY"]

all_employee_ids = supply_df["EMPLOYEE_ID"].unique()

# ==== NEW: eligible-but-rejected employees are only meaningfully explainable
# per project skill, so track "considered" employees (in eligibility view for
# that skill) per project for Enhancement 2 reporting later. ====
project_considered_employees = {}  # project_key -> set(employee_id)

for project_key, demand_rows in projects.items():

    opportunity_id, skill_id = project_key

    tier_pools = {t: {} for t in TIER_NAMES}

    considered = set()

    for employee_id in all_employee_ids:

        elig_key = (employee_id, skill_id)

        # Employee must be eligible for this skill at all
        if elig_key not in eligible_lookup:
            continue

        considered.add(employee_id)

        is_primary = eligibility_details[elig_key]["IS_PRIMARY"]

        months_ok = True
        worst_tier = "FULL_TIME"   # downgraded to PARTIAL if any month requires it
        month_hours = {}
        total_score = 0.0
        proficiency_values = []
        cost_rate_values = []

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
            cost_rate = float(supply_row["COST_RATE_HOURLY"])

            proficiency_values.append(proficiency)
            cost_rate_values.append(cost_rate)

            if eff_cap >= 160:
                availability_bonus = 100000
            elif eff_cap >= 80:
                availability_bonus = 200
            else:
                availability_bonus = 0

            # ==== MODIFIED: removed per-month is_primary*50 term ====
            total_score += (
                availability_bonus
                + proficiency * 20
                - cost_rate * 0.10
            )

        if not months_ok:
            continue

        # ==== MODIFIED: global, one-time tier bonuses (not per-month) ====
        if is_primary:
            total_score += PRIMARY_SKILL_PRIORITY_BONUS

        if worst_tier == "FULL_TIME":
            total_score += FULL_TIME_PRIORITY_BONUS

        tier_name = f"{worst_tier}_{'PRIMARY' if is_primary else 'SECONDARY'}"

        candidate_info = {
            "months": month_hours,
            "score": total_score,
            "capacity_tier": worst_tier,
            "is_primary": is_primary,
            "combined_tier": tier_name,
            "avg_proficiency": sum(proficiency_values) / len(proficiency_values),
            "avg_cost_rate": sum(cost_rate_values) / len(cost_rate_values),
            "availability_hours": 160.0 if worst_tier == "FULL_TIME" else 80.0
        }

        tier_pools[tier_name][employee_id] = candidate_info

    project_eligible_employees[project_key] = tier_pools
    project_considered_employees[project_key] = considered

eligible_project_count = sum(
    1 for v in project_eligible_employees.values()
    if any(v[t] for t in TIER_NAMES)
)

print(f"Projects With Eligible Employees : {eligible_project_count} / {len(projects)}")

# ==== informational summary of tier pool sizes (UNCHANGED intent, 4 tiers now) ====
print("\nProject Staffing Pool Summary (informational):")
for project_key, info in project_eligible_employees.items():
    req = project_required_fte[project_key]
    print(
        f"  {project_key} | Required FTE: {req['required_fte']} "
        f"(Total Demand: {req['total_demand_hours']}h) | "
        f"FT+Primary: {len(info['FULL_TIME_PRIMARY'])} | "
        f"Partial+Primary: {len(info['PARTIAL_PRIMARY'])} | "
        f"FT+Secondary: {len(info['FULL_TIME_SECONDARY'])} | "
        f"Partial+Secondary: {len(info['PARTIAL_SECONDARY'])}"
    )

# ============================================================
# Decision Variable Creation (multi-employee, four tiers)
# ==== MODIFIED: loops over all four tier pools instead of two ====
# ============================================================

print("\nCreating Decision Variables (Project-Level, Multi-Employee, Four-Tier)...")

decision_variables = {}
# (employee_id, project_key) -> solver BoolVar

variable_metadata = {}
# (employee_id, project_key) -> candidate_info

for project_key, info in project_eligible_employees.items():

    for tier_name in TIER_NAMES:

        for employee_id, candidate_info in info[tier_name].items():

            variable_name = (
                f"y_{employee_id}_"
                f"{project_key[0]}_{project_key[1]}_{tier_name}"
            )

            var = solver.BoolVar(variable_name)

            decision_variables[(employee_id, project_key)] = var
            variable_metadata[(employee_id, project_key)] = candidate_info

print(f"Decision Variables Created : {len(decision_variables)}")

# ============================================================
# 7. Display Sample Variables (UNCHANGED)
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
# Project Uniqueness Constraint (UNCHANGED - still intentionally skipped)
# ============================================================

print("\nProject Uniqueness Constraint skipped (multi-employee projects are allowed).")

# ============================================================
# Employee Capacity Constraints (UNCHANGED mechanism)
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
# Demand Constraints (UNCHANGED mechanism)
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

print("\nBuilding Objective Function...")

objective = solver.Objective()

for (employee_id, project_key), var in decision_variables.items():

    meta = variable_metadata[(employee_id, project_key)]
    objective.SetCoefficient(var, meta["score"])

objective.SetMaximization()

print("Objective Function Created Successfully.")

# ============================================================
# 11. Solve Optimization Model (UNCHANGED)
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
# Extract Solution
# ==== MODIFIED: BUSINESS_UNIT removed from output rows ====
# ============================================================

print("\nExtracting Solution...")

allocation_results = []

selected_pairs = set()   # ==== NEW: (employee_id, project_key) that were selected ====

for (employee_id, project_key), var in decision_variables.items():

    if var.solution_value() < 0.5:
        continue

    selected_pairs.add((employee_id, project_key))

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
            "SKILL_ID": demand["SKILL_ID"],
            "PERIOD_MONTH": period_month,
            "DEMAND_HOURS": demand["DEMAND_HOURS"],
            "ASSIGNED_HOURS": round(assigned_hours, 2),
            "PROFICIENCY": supply_row["PROFICIENCY"],
            "IS_PRIMARY": supply_row["IS_PRIMARY"],
            "COST_RATE_HOURLY": supply_row["COST_RATE_HOURLY"]

        })

# ==== MODIFIED: BUSINESS_UNIT removed from expected column list ====
allocation_columns = [
    "EMPLOYEE_ID",
    "DEMAND_ID",
    "OPPORTUNITY_ID",
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
# ==== NEW: ENHANCEMENT 2 - ENTERPRISE EXPLAINABILITY ====
# Everything below is additive. The existing allocation_df / output
# table above is untouched by any of this.
# ============================================================

print("\n" + "=" * 70)
print("Building Explainability Outputs")
print("=" * 70)

# ------------------------------------------------------------
# NEW: per-project stats used to decide "Highest Proficiency" /
# "Lowest Cost" / "Highest Optimization Score" tags, computed across
# every candidate considered eligible for that project (selected or not).
# ------------------------------------------------------------

project_stats = {}

for project_key, info in project_eligible_employees.items():

    all_candidates = {}
    for tier_name in TIER_NAMES:
        all_candidates.update(info[tier_name])

    if all_candidates:
        project_stats[project_key] = {
            "max_score": max(c["score"] for c in all_candidates.values()),
            "max_proficiency": max(c["avg_proficiency"] for c in all_candidates.values()),
            "min_cost_rate": min(c["avg_cost_rate"] for c in all_candidates.values()),
        }
    else:
        project_stats[project_key] = {"max_score": None, "max_proficiency": None, "min_cost_rate": None}

# ------------------------------------------------------------
# NEW: employee_id -> list of project_keys they were ultimately
# selected for (used to explain "already allocated elsewhere").
# ------------------------------------------------------------

employee_selected_projects = {}

for (employee_id, project_key) in selected_pairs:
    employee_selected_projects.setdefault(employee_id, []).append(project_key)

# ------------------------------------------------------------
# NEW: Selected-employee explainability rows (one per allocation_df row)
# ------------------------------------------------------------

explainability_selected_rows = []

for _, alloc in allocation_df.iterrows():

    employee_id = alloc["EMPLOYEE_ID"]
    project_key = (alloc["OPPORTUNITY_ID"], alloc["SKILL_ID"])
    meta = variable_metadata[(employee_id, project_key)]
    stats = project_stats[project_key]

    reasons = []

    if meta["is_primary"]:
        reasons.append("Primary Skill Match")
    else:
        reasons.append("Secondary Skill Utilized (Primary demand already satisfied)")

    reasons.append("Full-Time Resource" if meta["capacity_tier"] == "FULL_TIME" else "Partial Resource")

    if stats["max_proficiency"] is not None and meta["avg_proficiency"] >= stats["max_proficiency"]:
        reasons.append("Highest Proficiency")

    reasons.append("Available for all required months")

    if stats["min_cost_rate"] is not None and meta["avg_cost_rate"] <= stats["min_cost_rate"]:
        reasons.append("Lowest Cost")

    if stats["max_score"] is not None and meta["score"] >= stats["max_score"]:
        reasons.append("Highest Optimization Score")

    selection_reason = "Selected because " + "; ".join(f"\u2713 {r}" for r in reasons)

    explainability_selected_rows.append({
        "EMPLOYEE_ID": employee_id,
        "OPPORTUNITY_ID": alloc["OPPORTUNITY_ID"],
        "DEMAND_ID": alloc["DEMAND_ID"],
        "SKILL_ID": alloc["SKILL_ID"],
        "SKILL_TYPE": "Primary" if meta["is_primary"] else "Secondary",
        "EMPLOYMENT_TYPE": "Full-Time" if meta["capacity_tier"] == "FULL_TIME" else "Partial",
        "AVAILABILITY_HOURS": meta["availability_hours"],
        "PROFICIENCY": round(meta["avg_proficiency"], 2),
        "COST_RATE_HOURLY": round(meta["avg_cost_rate"], 2),
        "OPTIMIZATION_SCORE": round(meta["score"], 2),
        "SELECTION_REASON": selection_reason,
        "STATUS": "SELECTED"
    })

explainability_selected_df = pd.DataFrame(explainability_selected_rows)

print(f"\nExplainability Rows (Selected) : {len(explainability_selected_df)}")

# ------------------------------------------------------------
# NEW: Rejected-employee explainability rows.
# Scope: employees present in the eligibility view for a project's
# skill (i.e. "eligible employees") who were NOT selected for that
# project - either because they never qualified as a full-duration
# candidate, or because the solver did not pick their variable.
# ------------------------------------------------------------

explainability_rejected_rows = []

for project_key, considered in project_considered_employees.items():

    opportunity_id, skill_id = project_key

    info = project_eligible_employees[project_key]
    stats = project_stats[project_key]

    all_candidates = {}
    for tier_name in TIER_NAMES:
        all_candidates.update(info[tier_name])

    # Demand fully met for this project?
    project_demand_total = project_required_fte[project_key]["total_demand_hours"]
    project_allocated_total = allocation_df.loc[
        (allocation_df["OPPORTUNITY_ID"] == opportunity_id) &
        (allocation_df["SKILL_ID"] == skill_id),
        "ASSIGNED_HOURS"
    ].sum()
    demand_fully_met = project_allocated_total >= project_demand_total - 0.01

    for employee_id in considered:

        if (employee_id, project_key) in selected_pairs:
            continue   # was selected, not rejected

        if employee_id not in all_candidates:
            # Eligible for the skill, but failed the full-duration check
            reason = "Unavailable for required months (missing or zero-availability supply row in at least one required month)"
            explainability_rejected_rows.append({
                "EMPLOYEE_ID": employee_id,
                "OPPORTUNITY_ID": opportunity_id,
                "SKILL_ID": skill_id,
                "REJECTION_REASON": reason,
                "STATUS": "REJECTED"
            })
            continue

        meta = all_candidates[employee_id]

        reasons = []

        other_projects = [p for p in employee_selected_projects.get(employee_id, []) if p != project_key]
        if other_projects:
            reasons.append("Already allocated to another higher-priority skill/project (capacity exhausted)")

        if not meta["is_primary"]:
            primary_pool_size = len(info["FULL_TIME_PRIMARY"]) + len(info["PARTIAL_PRIMARY"])
            if primary_pool_size > 0:
                reasons.append("Primary-skilled employee preferred for this skill")

        if demand_fully_met:
            reasons.append("Insufficient remaining demand (project fully staffed by higher-priority candidates)")

        if not reasons:
            if stats["max_score"] is not None and meta["score"] < stats["max_score"]:
                reasons.append("Lower Optimization Score than selected candidates")
            if stats["min_cost_rate"] is not None and meta["avg_cost_rate"] > stats["min_cost_rate"]:
                reasons.append("Higher Cost than selected candidates")
            if stats["max_proficiency"] is not None and meta["avg_proficiency"] < stats["max_proficiency"]:
                reasons.append("Lower Proficiency than selected candidates")

        if not reasons:
            reasons.append("Lower Optimization Score")

        explainability_rejected_rows.append({
            "EMPLOYEE_ID": employee_id,
            "OPPORTUNITY_ID": opportunity_id,
            "SKILL_ID": skill_id,
            "REJECTION_REASON": "; ".join(reasons),
            "STATUS": "REJECTED"
        })

explainability_rejected_df = pd.DataFrame(explainability_rejected_rows)

print(f"Explainability Rows (Rejected) : {len(explainability_rejected_df)}")

# ------------------------------------------------------------
# NEW: Project Summary (per Opportunity + Skill)
# ------------------------------------------------------------

project_summary_rows = []

for project_key, demand_rows in projects.items():

    opportunity_id, skill_id = project_key

    demand_hours = sum(float(d["DEMAND_HOURS"]) for d in demand_rows)

    proj_alloc = allocation_df[
        (allocation_df["OPPORTUNITY_ID"] == opportunity_id) &
        (allocation_df["SKILL_ID"] == skill_id)
    ]

    allocated_hours = proj_alloc["ASSIGNED_HOURS"].sum()
    remaining_hours = max(demand_hours - allocated_hours, 0.0)

    selected_employees_here = {
        emp for (emp, pkey) in selected_pairs if pkey == project_key
    }

    ft_count = sum(
        1 for emp in selected_employees_here
        if variable_metadata[(emp, project_key)]["capacity_tier"] == "FULL_TIME"
    )
    partial_count = sum(
        1 for emp in selected_employees_here
        if variable_metadata[(emp, project_key)]["capacity_tier"] == "PARTIAL"
    )
    primary_count = sum(
        1 for emp in selected_employees_here
        if variable_metadata[(emp, project_key)]["is_primary"]
    )
    secondary_count = sum(
        1 for emp in selected_employees_here
        if not variable_metadata[(emp, project_key)]["is_primary"]
    )

    if remaining_hours <= 0.01:
        reason = "Demand fully satisfied."
    else:
        info = project_eligible_employees[project_key]
        unused_ft_primary = len(info["FULL_TIME_PRIMARY"]) - sum(
            1 for emp in selected_employees_here if emp in info["FULL_TIME_PRIMARY"]
        )
        if unused_ft_primary <= 0 and len(info["FULL_TIME_PRIMARY"]) > 0:
            reason = ("Insufficient Full-Time employees available. Primary-skilled "
                       "employees exhausted; remaining demand filled using secondary-skilled "
                       "resources wherever possible.")
        elif not any(info[t] for t in TIER_NAMES):
            reason = "No eligible employees found for this skill across all required months."
        else:
            reason = "Eligible candidate pool exhausted before demand was fully met."

    project_summary_rows.append({
        "OPPORTUNITY_ID": opportunity_id,
        "SKILL_ID": skill_id,
        "DEMAND_HOURS": round(demand_hours, 2),
        "ALLOCATED_HOURS": round(allocated_hours, 2),
        "REMAINING_HOURS": round(remaining_hours, 2),
        "FULL_TIME_EMPLOYEES": ft_count,
        "PARTIAL_EMPLOYEES": partial_count,
        "PRIMARY_ALLOCATIONS": primary_count,
        "SECONDARY_ALLOCATIONS": secondary_count,
        "REASON_FOR_REMAINING_DEMAND": reason
    })

project_summary_df = pd.DataFrame(project_summary_rows)

print(f"Project Summary Rows : {len(project_summary_df)}")

# ------------------------------------------------------------
# NEW: Overall Optimization Summary
# ------------------------------------------------------------

total_demand_hours = project_summary_df["DEMAND_HOURS"].sum()
total_allocated_hours = project_summary_df["ALLOCATED_HOURS"].sum()
total_unallocated_hours = project_summary_df["REMAINING_HOURS"].sum()
allocation_pct = (total_allocated_hours / total_demand_hours * 100) if total_demand_hours > 0 else 0.0

total_ft = project_summary_df["FULL_TIME_EMPLOYEES"].sum()
total_partial = project_summary_df["PARTIAL_EMPLOYEES"].sum()
total_primary = project_summary_df["PRIMARY_ALLOCATIONS"].sum()
total_secondary = project_summary_df["SECONDARY_ALLOCATIONS"].sum()

overall_summary_df = pd.DataFrame([{
    "TOTAL_DEMAND_HOURS": round(total_demand_hours, 2),
    "ALLOCATED_HOURS": round(total_allocated_hours, 2),
    "UNALLOCATED_HOURS": round(total_unallocated_hours, 2),
    "ALLOCATION_PERCENTAGE": round(allocation_pct, 2),
    "TOTAL_FULL_TIME_ALLOCATIONS": int(total_ft),
    "TOTAL_PARTIAL_ALLOCATIONS": int(total_partial),
    "TOTAL_PRIMARY_SKILL_ALLOCATIONS": int(total_primary),
    "TOTAL_SECONDARY_SKILL_ALLOCATIONS": int(total_secondary)
}])

print("\nOverall Optimization Summary")
print(overall_summary_df.to_string(index=False))

# ============================================================
# 13. Write Results to Snowflake
# ==== MODIFIED: BUSINESS_UNIT removed from allocation_df column list ====
# ==== NEW: three additional explainability tables written ====
# ============================================================

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

    allocation_df["RUN_TS"] = pd.Timestamp.now()
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

    # ==== MODIFIED: BUSINESS_UNIT removed from final column arrangement ====
    allocation_df = allocation_df[
        [
            "RUN_TS",
            "EMPLOYEE_ID",
            "DEMAND_ID",
            "OPPORTUNITY_ID",
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

    snow_df = session.create_dataframe(allocation_df)

    snow_df.write.mode("overwrite").save_as_table(
        "IRM_DATABASE.OPERATIONAL.OPTIMIZER_ALLOCATION_PLAN"
    )

    print("=" * 70)
    print("Allocation Plan Successfully Written to Snowflake")
    print("=" * 70)
    print(f"Rows Written : {len(allocation_df)}")

    # ==== NEW: write the three explainability outputs as separate tables ====

    run_ts = pd.Timestamp.now()

    if not explainability_selected_df.empty:
        explainability_selected_df["RUN_TS"] = run_ts
        session.create_dataframe(explainability_selected_df).write.mode("overwrite").save_as_table(
            "IRM_DATABASE.OPERATIONAL.OPTIMIZER_EXPLAINABILITY_SELECTED"
        )
        print(f"Explainability (Selected) Written : {len(explainability_selected_df)} rows")

    if not explainability_rejected_df.empty:
        explainability_rejected_df["RUN_TS"] = run_ts
        session.create_dataframe(explainability_rejected_df).write.mode("overwrite").save_as_table(
            "IRM_DATABASE.OPERATIONAL.OPTIMIZER_EXPLAINABILITY_REJECTED"
        )
        print(f"Explainability (Rejected) Written : {len(explainability_rejected_df)} rows")

    if not project_summary_df.empty:
        project_summary_df["RUN_TS"] = run_ts
        session.create_dataframe(project_summary_df).write.mode("overwrite").save_as_table(
            "IRM_DATABASE.OPERATIONAL.OPTIMIZER_PROJECT_SUMMARY"
        )
        print(f"Project Summary Written : {len(project_summary_df)} rows")

    overall_summary_df["RUN_TS"] = run_ts
    session.create_dataframe(overall_summary_df).write.mode("overwrite").save_as_table(
        "IRM_DATABASE.OPERATIONAL.OPTIMIZER_OVERALL_SUMMARY"
    )
    print("Overall Summary Written : 1 row")

    print("=" * 70)
    print("All Explainability Outputs Written to Snowflake")
    print("=" * 70)