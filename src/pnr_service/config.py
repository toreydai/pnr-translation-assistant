import os


PRIMARY_MODEL_ID = os.getenv("PRIMARY_MODEL_ID", "moonshotai.kimi-k2.5")
REVIEW_MODEL_ID = os.getenv("REVIEW_MODEL_ID", "moonshot.kimi-k2-thinking")
TRANSLATIONS_TABLE = os.getenv("TRANSLATIONS_TABLE", "")
EXECUTIONS_TABLE = os.getenv("EXECUTIONS_TABLE", "")
COMMAND_BUCKET = os.getenv("COMMAND_BUCKET", "")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "secure-commands/")
DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "default")
AUTO_EXECUTION_ENABLED = os.getenv("AUTO_EXECUTION_ENABLED", "false").lower() == "true"
WEB_URL = os.getenv("WEB_URL", "")
