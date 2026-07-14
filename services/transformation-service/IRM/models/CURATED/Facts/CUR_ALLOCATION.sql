{{ config(
    materialized='incremental',
    unique_key='ALLOCATION_ID',
    incremental_strategy='merge'
) }}

select
  md5(ALLOCATION_ID) as ALLOCATION_SK,
    ALLOCATION_ID,

    PROJECT_ID,

    TASK_ID,

    EMPLOYEE_ID,

    SKILL_ID,

    PERIOD_MONTH,

    ALLOCATED_HOURS

from {{ source('raw','SMARTSHEET_ALLOCATIONS') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(CREATED_AT),'1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}

qualify row_number() over
(
    partition by ALLOCATION_ID
    order by CREATED_AT desc
)=1