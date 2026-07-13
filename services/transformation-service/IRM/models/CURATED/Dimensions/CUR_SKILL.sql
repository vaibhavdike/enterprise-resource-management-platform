{{ config(
    materialized='table'
) }}

select distinct
   md5(SKILL_ID) as SKILL_SK,
    SKILL_ID,
    

from
(

    select PRIMARY_SKILL_ID as SKILL_ID
    from {{ source('raw','ADP_EMPLOYEES') }}

    union

    select SKILL_ID
    from {{ source('raw','ADP_EMPLOYEE_SKILLS') }}

    union

    select REQUIRED_SKILL_ID
    from {{ source('raw','SMARTSHEET_TASKS') }}

    union

    select SKILL_ID
    from {{ source('raw','SMARTSHEET_ALLOCATIONS') }}

    union

    select SKILL_ID
    from {{ source('raw','NETSUITE_PIPELINE_SKILL_DEMAND') }}

    union

    select SKILL_ID
    from {{ source('raw','DEMAND_HISTORY') }}

    union

    select SKILL_ID
    from {{ source('raw','RESOURCE_GAPS_HISTORY') }}

)

where SKILL_ID is not null