from abc import ABC, abstractmethod


class FinanceProvider(ABC):
    name = "base"

    @abstractmethod
    def get_snapshot(self, ticker: str):
        """Return FinancialSnapshot. Raise TickerNotFound if unknown; any other exception = provider fault."""


class SearchProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 5):
        """Return list[SourceDoc]."""
