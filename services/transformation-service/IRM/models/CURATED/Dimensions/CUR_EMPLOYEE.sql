{{ config(
    materialized='incremental',
    unique_key='EMPLOYEE_ID',
    incremental_strategy='merge'
) }}

select
    md5(EMPLOYEE_ID) as EMPLOYEE_SK,
    EMPLOYEE_ID,
    ROLE,
    LEVEL,
    BUSINESS_UNIT,
    LOCATION,
    PRIMARY_SKILL_ID,
    COST_RATE_HOURLY,
    try_to_date(HIRE_DATE) as HIRE_DATE,
    EMPLOYMENT_STATUS,
    CREATED_AT

from {{ source('raw', 'ADP_EMPLOYEES') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(CREATED_AT), '1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}