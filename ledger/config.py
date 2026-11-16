import logging
import os

from dotenv import load_dotenv


class BrokerCallbackLogFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            if isinstance(args[2], str) and args[2].startswith("/broker/callback"):
                args[2] = "/broker/callback"
                record.args = tuple(args)
        return True


def load_config():
    """Load local credentials while giving deployed environment variables precedence."""
    # Alpha Vantage authenticates in the query string. Keep URLs out of INFO logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, BrokerCallbackLogFilter) for f in logger.filters):
        logger.addFilter(BrokerCallbackLogFilter())
    load_dotenv(".env")
    for canonical, alias in (
        ("LLM_API_KEY", "OPENAI_KEY"),
        ("LLM_API_KEY", "OPENAI_API_KEY"),
        ("ALPHAVANTAGE_API_KEY", "ALPHA_VANTAGE"),
        ("APCA_API_KEY_ID", "ALPACA_key"),
        ("APCA_API_SECRET_KEY", "ALPACA_secret"),
    ):
        if not os.getenv(canonical) and os.getenv(alias):
            os.environ[canonical] = os.environ[alias]
    if os.getenv("LLM_API_KEY") and not os.getenv("LLM_MODEL"):
        os.environ["LLM_MODEL"] = "gpt-4o-mini"
