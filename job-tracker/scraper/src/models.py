from pydantic import BaseModel


class CompanyConfig(BaseModel):
    name: str
    ats: str  # 'greenhouse' | 'lever' | 'playwright' | 'html'
    greenhouse_id: str | None = None
    lever_id: str | None = None
    careers_url: str | None = None
    job_selector: str | None = None       # CSS selector hint for html scraper
    location_filter: str | None = None    # overrides ScraperConfig.default_location_filter
    acciona_division: str | None = None   # divisionID for AccionaScraper (e.g. "Bestinver_Business_Line")


class ScraperConfig(BaseModel):
    default_location_filter: str
    companies: list[CompanyConfig]


class Job(BaseModel):
    title: str
    url: str
    location: str | None = None
    department: str | None = None
    job_type: str | None = None
    description: str | None = None
    external_id: str | None = None        # ATS-native ID (Greenhouse/Lever); None for HTML/Playwright
