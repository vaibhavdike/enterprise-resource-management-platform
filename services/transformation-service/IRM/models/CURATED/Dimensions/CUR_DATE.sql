{{ config(
    materialized='table'
) }}

with all_dates as (

    select PERIOD_MONTH from {{ source('raw','ADP_AVAILABILITY') }}

    union

    select PERIOD_MONTH from {{ source('raw','NETSUITE_FINANCIAL_ACTUALS') }}

    union

    select PERIOD_MONTH from {{ source('raw','DEMAND_HISTORY') }}

    union

    select PERIOD_MONTH from {{ source('raw','RESOURCE_GAPS_HISTORY') }}

    union

    select START_DATE from {{ source('raw','SMARTSHEET_PROJECTS') }}

    union

    select END_DATE from {{ source('raw','SMARTSHEET_PROJECTS') }}

    union

    select TASK_START from {{ source('raw','SMARTSHEET_TASKS') }}

    union

    select TASK_END from {{ source('raw','SMARTSHEET_TASKS') }}


)

select

    PERIOD_MONTH,

    year(PERIOD_MONTH) as YEAR,

    month(PERIOD_MONTH) as MONTH,

    monthname(PERIOD_MONTH) as MONTH_NAME,

    quarter(PERIOD_MONTH) as QUARTER_NUMBER,

    concat('Q', quarter(PERIOD_MONTH)) as QUARTER,

    weekofyear(PERIOD_MONTH) as WEEK_OF_YEAR,

    dayofweek(PERIOD_MONTH) as DAY_OF_WEEK,

    dayname(PERIOD_MONTH) as DAY_NAME,

    dayofmonth(PERIOD_MONTH) as DAY_OF_MONTH,

    dayofyear(PERIOD_MONTH) as DAY_OF_YEAR,

    last_day(PERIOD_MONTH) as MONTH_END_DATE,

    date_trunc('month', PERIOD_MONTH) as MONTH_START_DATE,

    concat(year(PERIOD_MONTH), '-', lpad(month(PERIOD_MONTH),2,'0')) as FISCAL_PERIOD

from all_dates