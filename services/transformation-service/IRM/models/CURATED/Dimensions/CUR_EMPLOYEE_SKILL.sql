{{config(
    materialized='incremental',
    unique_key=['EMPLOYEE_ID','SKILL_ID'],
    incremental_strategy='merge'
)}}

SELECT
 md5(EMPLOYEE_ID || '|' || SKILL_ID) AS EMPLOYEE_SKILL_SK,
   EMPLOYEE_ID,
   SKILL_ID,
   PROFICIENCY,
   IS_PRIMARY,
   CREATED_AT
FROM {{ source('raw', 'ADP_EMPLOYEE_SKILLS') }}

{%if is_incremental()%}

WHERE CREATED_AT >
(
    SELECT COALESCE(MAX(CREATED_AT),'1900-01-01'::timestamp_ntz)
    FROM {{ this }}
)

{%endif%}