{{ config(
    materialized='incremental',
    unique_key='TASK_ID',
    incremental_strategy='merge'
) }}

select

    md5(TASK_ID) as TASK_SK,

    TASK_ID,

    PROJECT_ID,

    trim(PHASE) as PHASE,

    REQUIRED_SKILL_ID,

    PLANNED_HOURS,

    TASK_START,

    TASK_END,

    CREATED_AT

from {{ source('raw', 'SMARTSHEET_TASKS') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(CREATED_AT), '1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}

qualify row_number() over (
    partition by TASK_ID
    order by CREATED_AT desc
) = 1