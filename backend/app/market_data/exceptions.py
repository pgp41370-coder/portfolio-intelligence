"""Market-data errors.

Messages are written to be safe to log and store: they never contain credentials.
"""


class MarketDataError(Exception):
    """Base class for market-data failures."""


class ProviderNotConfiguredError(MarketDataError):
    """The provider needs credentials that are not configured."""


class ProviderAuthenticationError(MarketDataError):
    """The provider rejected the credentials (HTTP 401, 403, or 400 reporting an API key problem). Never retried."""


class ProviderRequestError(MarketDataError):
    """The provider rejected a single request (e.g. HTTP 400 bad request, unknown symbol). Never retried."""


class ProviderNotFoundError(ProviderRequestError):
    """The provider has no data for the requested security."""


class ProviderRateLimitError(MarketDataError):
    """HTTP 429: rate limit reached or monthly credits exhausted. The sync stops immediately."""


class ProviderUnavailableError(MarketDataError):
    """Timeouts, network failures or HTTP 5xx after bounded retries."""


class ProviderResponseError(MarketDataError):
    """The response did not match the documented format. Nothing from it is stored."""


class ProviderGranularityError(ProviderResponseError):
    """The price series is not confirmed to be daily (for example weekly aggregates)."""


class RequestBudgetExceededError(MarketDataError):
    """The monthly request budget is used up. The request was not sent."""


class SyncAlreadyRunningError(MarketDataError):
    """Another market-data sync holds the database lock."""
