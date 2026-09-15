"""Monthly request budget for metered provider calls."""

from app.market_data.exceptions import RequestBudgetExceededError


class RequestBudget:
    """Counts metered requests this month (earlier runs plus this run) against a hard limit.

    ``consume`` is called immediately before every metered request, including retries. It
    raises instead of allowing a request that would exceed the limit.
    """

    def __init__(self, *, limit: int, used_before_run: int) -> None:
        if limit < 1:
            raise ValueError("The request budget must allow at least one request.")
        self.limit = limit
        self.used_before_run = max(0, used_before_run)
        self.used_in_run = 0

    @property
    def used(self) -> int:
        return self.used_before_run + self.used_in_run

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def consume(self) -> None:
        if self.used >= self.limit:
            raise RequestBudgetExceededError(
                f"Monthly market-data request budget reached: {self.used} of {self.limit} requests used. "
                "The sync stopped without sending another request."
            )
        self.used_in_run += 1
