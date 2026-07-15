# ============================================================
# optimizer.py
# Intelligent Resource Allocation using Google OR-Tools
# ============================================================
import os
from snowflake.snowpark import Session
from ortools.linear_solver import pywraplp
import pandas as pd

# ============================================================
# 1. Snowflake Connection
# ============================================================ 


# for local development 

connection_parameters = {
    "account": "A4357138117071-ACCELIRATE_PARTNER",
    "user": "VAIBHAVDIKE",
    "password": "Vaibhav@123456789",  
    "role": "SYSADMIN",
    "warehouse": "DEMO_WH",
    "database": "IRM_DB",
    "schema": "OPERATIONAL"
}

session = Session.builder.configs(connection_parameters).create() 



# for production 

# import os


# connection_params = {
#     "host": os.environ["SNOWFLAKE_HOST"],
#     "account": os.environ["SNOWFLAKE_ACCOUNT"],
#     "authenticator": "oauth",
#     "token": open("/snowflake/session/token").read().strip(),
#     "warehouse": "DEMO_WH",
#     "database": "IRM_DB",
#     "schema": "OPERATIONAL"
# }

# session = Session.builder.configs(connection_params).create()

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
# 6. Create Decision Variables
# ============================================================

print("\nCreating Decision Variables...")

decision_variables = {}

for _, demand in demand_df.iterrows():

    for _, supply in supply_df.iterrows():

        # Match Month
        same_month = (
            supply["PERIOD_MONTH"] ==
            demand["PERIOD_MONTH"]
        )

        # Match Skill
        same_skill = (
            supply["SKILL_ID"] ==
            demand["SKILL_ID"]
        )

        # Match Business Unit
        same_bu = (
            supply["BUSINESS_UNIT"] ==
            demand["BUSINESS_UNIT"]
        )

        # Employee Eligible?
        employee_skill = (
            supply["EMPLOYEE_ID"],
            supply["SKILL_ID"]
        )

        eligible = employee_skill in eligible_lookup

        if same_month and same_skill and same_bu and eligible:

            variable_name = (
                f"x_{supply['EMPLOYEE_ID']}"
                f"_{demand['DEMAND_ID']}"
            )

            decision_variables[
                (
                    supply["EMPLOYEE_ID"],
                    demand["DEMAND_ID"]
                )
            ] = solver.NumVar(
                0,
                solver.infinity(),
                variable_name
            )

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
# 8. Employee Capacity Constraints
# ============================================================

print("\nAdding Employee Capacity Constraints...")

capacity_constraints = 0

# Group supply by Employee + Month
employee_capacity = (
    supply_df
    .groupby(["EMPLOYEE_ID", "PERIOD_MONTH"])
    .first()
    .reset_index()
)

for _, emp in employee_capacity.iterrows():

    employee_id = emp["EMPLOYEE_ID"]
    period_month = emp["PERIOD_MONTH"]
    capacity = float(emp["CAPACITY_HOURS"])

    constraint = solver.Constraint(
        0,
        capacity,
        f"Capacity_{employee_id}_{period_month}"
    )

    # Find all variables belonging to this employee & month
    for (emp_id, demand_id), var in decision_variables.items():

        if emp_id != employee_id:
            continue

        demand_row = demand_df[
            demand_df["DEMAND_ID"] == demand_id
        ].iloc[0]

        if demand_row["PERIOD_MONTH"] == period_month:

            constraint.SetCoefficient(var, 1)

    capacity_constraints += 1

print(f"Capacity Constraints Added : {capacity_constraints}")  

# ============================================================
# 9. Demand Constraints
# ============================================================

print("\nAdding Demand Constraints...")

demand_constraints = 0

for _, demand in demand_df.iterrows():

    demand_id = demand["DEMAND_ID"]
    required_hours = float(demand["DEMAND_HOURS"])

    constraint = solver.Constraint(
        0,
        required_hours,
        f"Demand_{demand_id}"
    )

    # Find all employees that can work on this demand
    for (employee_id, d_id), var in decision_variables.items():

        if d_id == demand_id:
            constraint.SetCoefficient(var, 1)

    demand_constraints += 1

print(f"Demand Constraints Added : {demand_constraints}") 

# ============================================================
# 10. Objective Function
# ============================================================

print("\nBuilding Objective Function...")

objective = solver.Objective()

for (employee_id, demand_id), var in decision_variables.items():

    demand = demand_df[
        demand_df["DEMAND_ID"] == demand_id
    ].iloc[0]

    supply = supply_df[
        (supply_df["EMPLOYEE_ID"] == employee_id) &
        (supply_df["SKILL_ID"] == demand["SKILL_ID"]) &
        (supply_df["PERIOD_MONTH"] == demand["PERIOD_MONTH"])
    ].iloc[0]

    proficiency = float(supply["PROFICIENCY"])

    is_primary = 1 if supply["IS_PRIMARY"] else 0

    cost_rate = float(supply["COST_RATE_HOURLY"])

    capacity_hours = float(supply["CAPACITY_HOURS"])
    # Prefer employees with full availability
    if capacity_hours >= 160:
        availability_bonus = 1000
    elif capacity_hours >= 120:
        availability_bonus = 500
    elif capacity_hours >= 80:
        availability_bonus = 200
    else:
        availability_bonus = 0

    score = (
        availability_bonus 
        +proficiency * 100
        + is_primary * 50
        - cost_rate * 0.10
    )

    objective.SetCoefficient(var, score)

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
# 12. Extract Solution
# ============================================================

print("\nExtracting Solution...")

allocation_results = []

for (employee_id, demand_id), var in decision_variables.items():

    assigned_hours = var.solution_value()

    if assigned_hours > 0.001:

        demand = demand_df[
            demand_df["DEMAND_ID"] == demand_id
        ].iloc[0]

        supply = supply_df[
            (supply_df["EMPLOYEE_ID"] == employee_id)
            &
            (supply_df["SKILL_ID"] == demand["SKILL_ID"])
            &
            (supply_df["PERIOD_MONTH"] == demand["PERIOD_MONTH"])
        ].iloc[0]

        allocation_results.append({

            "EMPLOYEE_ID": employee_id,

            "DEMAND_ID": demand_id,

            "OPPORTUNITY_ID": demand["OPPORTUNITY_ID"],

            "BUSINESS_UNIT": demand["BUSINESS_UNIT"],

            "SKILL_ID": demand["SKILL_ID"],

            "PERIOD_MONTH": demand["PERIOD_MONTH"],

            "DEMAND_HOURS": demand["DEMAND_HOURS"],

            "ASSIGNED_HOURS": round(assigned_hours, 2),

            "PROFICIENCY": supply["PROFICIENCY"],

            "IS_PRIMARY": supply["IS_PRIMARY"],

            "COST_RATE_HOURLY": supply["COST_RATE_HOURLY"]

          })
allocation_df = pd.DataFrame(allocation_results)

print(f"\nAssignments Created : {len(allocation_df)}")

print("\nSample Allocation")

print(allocation_df.head(10)) 

# ============================================================
# 13. Write Results to Snowflake
# ============================================================

from datetime import datetime
import pandas as pd

print("\nWriting Allocation Plan to Snowflake...")

# ------------------------------------------------------------
# Add Run Timestamp
# ------------------------------------------------------------
allocation_df["RUN_TS"] = pd.Timestamp.now()

# ------------------------------------------------------------
# Convert datatypes
# ------------------------------------------------------------
allocation_df["PERIOD_MONTH"] = pd.to_datetime(allocation_df["PERIOD_MONTH"])

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


