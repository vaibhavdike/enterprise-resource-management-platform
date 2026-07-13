{{ config(
    materialized='incremental',
    unique_key=['PROJECT_ID', 'PERIOD_MONTH'],
    incremental_strategy='merge'
) }}

select
md5(PROJECT_ID || '|' || PERIOD_MONTH) as PROJECT_FINANCIALS_SK,

    PROJECT_ID,

    PERIOD_MONTH,

    BOOKED_HOURS,

    ACTUAL_HOURS,

    BOOKED_COST,

    ACTUAL_COST,

    CREATED_AT as _UPDATED_AT

from {{ source('raw', 'NETSUITE_FINANCIAL_ACTUALS') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(_UPDATED_AT), '1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}

qualify row_number() over (
    partition by PROJECT_ID, PERIOD_MONTH
    order by CREATED_AT desc
) = 1