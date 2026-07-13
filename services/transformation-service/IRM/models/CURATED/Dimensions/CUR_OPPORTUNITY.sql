{{ config(
    materialized='incremental',
    unique_key='OPPORTUNITY_ID',
    incremental_strategy='merge'
) }}

select

    md5(OPPORTUNITY_ID) as OPPORTUNITY_SK,

    OPPORTUNITY_ID,

    trim(BUSINESS_UNIT) as BUSINESS_UNIT,

    ESTIMATED_VALUE,

    EXPECTED_START,

    PRIORITY,

    upper(trim(STAGE)) as STAGE,

    WIN_PROBABILITY,

    CREATED_AT

from {{ source('raw', 'NETSUITE_PIPELINE_OPPORTUNITIES') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(CREATED_AT), '1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}

qualify row_number() over (
    partition by OPPORTUNITY_ID
    order by CREATED_AT desc
) = 1