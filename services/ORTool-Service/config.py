from snowflake.snowpark import Session

connection_parameters = {
    "account": "A4357138117071-ACCELIRATE_PARTNER",
    "user": "VAIBHAVDIKE",
    "password": "Vaibhav@123456789",
    "role": "SYSADMIN",
    "warehouse": "DEMO_WH",
    "database": "IRM_DB",
    "schema": "OPERATIONAL"
}

session = Session.builder.configs(connection_parameters).create()