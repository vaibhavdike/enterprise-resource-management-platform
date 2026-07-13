{{ config(
    materialized='incremental',
    unique_key=['EMPLOYEE_ID', 'PERIOD_MONTH'],
    incremental_strategy='merge'
) }}

select

    EMPLOYEE_ID,

    PERIOD_MONTH,

    FTE_FRACTION,

    PTO_HOURS,

    CAPACITY_HOURS,

    CREATED_AT as _UPDATED_AT

from {{ source('raw', 'ADP_AVAILABILITY') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(_UPDATED_AT), '1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}

qualify row_number() over (
    partition by EMPLOYEE_ID, PERIOD_MONTH
    order by CREATED_AT desc
) = 1