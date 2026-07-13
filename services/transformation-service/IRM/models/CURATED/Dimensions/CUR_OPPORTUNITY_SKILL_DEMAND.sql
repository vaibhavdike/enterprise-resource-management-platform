{{config(
    materialized='incremental',
    unique_key='OPPORTUNITY_ID',
    incremental_strategy='merge'
)
}}

SELECT
 
  MD5(OPPORTUNITY_ID) AS OPPORTUNITY_SK,
  OPPORTUNITY_ID,
   SKILL_ID,
   EXPECTED_HOURS,
   CREATED_AT
   FROM {{source('raw','NETSUITE_PIPELINE_SKILL_DEMAND')}}
  
  {% if is_incremental()%}
  where CREATED_AT > (
    select coalesce(max(CREATED_AT), '1900-01-01'::timestamp_ntz)
    from {{this}}
  )
  {% endif %}