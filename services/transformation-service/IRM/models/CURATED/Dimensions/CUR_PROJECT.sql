{{ config(
    materialized='incremental',
    unique_key='PROJECT_ID',
    incremental_strategy='merge'
) }}

select

    md5(PROJECT_ID) as PROJECT_SK,

    PROJECT_ID,

    trim(PROJECT_NAME) as PROJECT_NAME,

    trim(BUSINESS_UNIT) as BUSINESS_UNIT,

    PRIORITY,

    START_DATE,

    END_DATE,

    upper(trim(STATUS)) as STATUS,

    ESTIMATED_MARGIN_PCT,

    STRATEGIC_VALUE,

    CREATED_AT

from {{ source('raw', 'SMARTSHEET_PROJECTS') }}

{% if is_incremental() %}

where CREATED_AT >
(
    select coalesce(max(CREATED_AT), '1900-01-01'::timestamp_ntz)
    from {{ this }}
)

{% endif %}

qualify row_number() over (
    partition by PROJECT_ID
    order by CREATED_AT desc
) = 1