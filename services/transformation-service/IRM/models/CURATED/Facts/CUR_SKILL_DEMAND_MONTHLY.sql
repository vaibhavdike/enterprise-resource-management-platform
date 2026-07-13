{{ config(
    materialized='incremental',
    unique_key=['PERIOD_MONTH', 'SKILL_ID', 'BUSINESS_UNIT'],
    incremental_strategy='merge'
) }}

select
   md5(PERIOD_MONTH || '|' || SKILL_ID || '|' || upper(trim(BUSINESS_UNIT))) as SKILL_DEMAND_MONTHLY_SK,
    PERIOD_MONTH,

    SKILL_ID,

    upper(trim(BUSINESS_UNIT)) as BUSINESS_UNIT,

    DEMAND_HOURS,

    IS_ACTUAL,

    CREATED_AT as _UPDATED_AT

from {{ source('raw', 'DEMAND_HISTORY') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(_UPDATED_AT), '1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}

qualify row_number() over (
    partition by PERIOD_MONTH, SKILL_ID, BUSINESS_UNIT
    order by CREATED_AT desc
) = 1