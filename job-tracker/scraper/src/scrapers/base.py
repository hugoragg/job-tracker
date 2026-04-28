from abc import ABC, abstractmethod

from ..models import CompanyConfig, Job


class BaseScraper(ABC):
    def __init__(self, company: CompanyConfig, default_location_filter: str) -> None:
        self.company = company
        self.location_filter = company.location_filter or default_location_filter

    @abstractmethod
    async def fetch_jobs(self) -> list[Job]:
        ...

    def matches_location(self, text: str | None) -> bool:
        if not text:
            return False
        return self.location_filter.lower() in text.lower()
