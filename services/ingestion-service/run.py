from app.config.settings import settings

print("=" * 50)
print("Application :", settings.APP_NAME)
print("Environment :", settings.ENV)

print("\nAWS")
print(settings.AWS_BUCKET_NAME)
print(settings.AWS_REGION)

print("\nSnowflake")
print(settings.SNOWFLAKE_ACCOUNT)
print(settings.SNOWFLAKE_DATABASE)
print(settings.SNOWFLAKE_WAREHOUSE)

print("=" * 50)