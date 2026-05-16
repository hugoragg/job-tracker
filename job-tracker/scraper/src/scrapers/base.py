import re
from abc import ABC, abstractmethod

from ..models import CompanyConfig, Job

# When filtering for a Spanish city, also accept country-level matches.
# Some job boards show "Spain" instead of the specific city.
_LOCATION_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "madrid": ("madrid", "spain", "españa", "espana"),
    "barcelona": ("barcelona", "spain", "españa", "espana"),
    "bilbao": ("bilbao", "spain", "españa", "espana"),
    "valencia": ("valencia", "spain", "españa", "espana"),
    "sevilla": ("sevilla", "seville", "spain", "españa", "espana"),
    "london": ("london", "uk", "u.k.", "united kingdom", "england", "great britain"),
}

# Splits a location_filter string into individual city filters. Supports
# `,` (e.g. "Madrid, London") and `|` (e.g. "Madrid|London") as separators
# so configs can mirror the URL syntax of multi-city career boards.
_FILTER_SPLIT_RE = re.compile(r"\s*[,|]\s*")

# Spanish cities — used to reject country-level matches when the text actually
# names a different city. ("Madrid" filter shouldn't accept a job whose
# context is "Sevilla, Spain".)
_SPANISH_CITIES: frozenset[str] = frozenset({
    "madrid", "barcelona", "bilbao", "valencia", "sevilla", "seville",
    "zaragoza", "malaga", "málaga", "murcia", "palma", "las palmas",
    "alicante", "vigo", "gijón", "gijon", "córdoba", "cordoba", "valladolid",
    "vitoria", "granada", "elche", "oviedo", "santander", "pamplona", "donostia",
    "san sebastián", "san sebastian", "albacete", "burgos", "salamanca",
    "huelva", "lleida", "tarragona", "leon", "león", "cádiz", "cadiz",
    "logroño", "logrono", "badajoz", "almería", "almeria", "girona", "toledo",
})

# UK cities — symmetric to Spanish cities. Filtering on "London" expands to
# country-level terms (uk, united kingdom, england), which would otherwise
# wrongly accept a "Glasgow, United Kingdom" posting. Listing other major UK
# cities lets us reject them explicitly.
_UK_CITIES: frozenset[str] = frozenset({
    "london", "glasgow", "edinburgh", "manchester", "birmingham", "liverpool",
    "bristol", "leeds", "sheffield", "newcastle", "cardiff", "belfast",
    "nottingham", "leicester", "coventry", "southampton", "brighton",
    "aberdeen", "dundee", "oxford", "cambridge", "york", "bath", "reading",
    "milton keynes", "swansea", "portsmouth", "plymouth", "hull",
})

_WORD_BOUNDARY_RE = re.compile(r"\W+")


class BaseScraper(ABC):
    def __init__(self, company: CompanyConfig, default_location_filter: str) -> None:
        self.company = company
        self.location_filter = company.location_filter or default_location_filter

    @abstractmethod
    async def fetch_jobs(self) -> list[Job]:
        ...

    def matches_location(self, text: str | None) -> bool:
        """True if `text` plausibly indicates one of the configured locations.

        The `location_filter` may be a single city ("Madrid") or a
        pipe-/comma-separated list ("Madrid|London"). A job matches if **any**
        configured city accepts it. For each city we accept either the city
        itself or its country-level expansion (e.g. "Spain", "UK"), but reject
        text that mentions a *different* Spanish city not in the filter set
        (so a "Madrid" filter doesn't pass a "Sevilla, Spain" job).
        """
        if not text:
            return False
        text_lower = text.lower()
        tokens = set(t for t in _WORD_BOUNDARY_RE.split(text_lower) if t)

        configured = [f.lower() for f in _FILTER_SPLIT_RE.split(self.location_filter) if f.strip()]

        # Compose the union of acceptable terms and the set of regional peer
        # cities we'd accept (so we only reject *other* peer cities).
        accepted_terms: list[str] = []
        accepted_peer_cities: set[str] = set()
        for filt in configured:
            accepted_terms.extend(_LOCATION_EXPANSIONS.get(filt, (filt,)))
            if filt in _SPANISH_CITIES or filt in _UK_CITIES:
                accepted_peer_cities.add(filt)

        # Reject if a peer city we *didn't* configure appears in the text.
        # Only enforce within each region the user actually filtered on — if
        # the filter is Madrid-only we don't need to reject Glasgow (no UK
        # expansion is in play) and vice versa.
        peer_groups: list[frozenset[str]] = []
        if accepted_peer_cities & _SPANISH_CITIES:
            peer_groups.append(_SPANISH_CITIES)
        if accepted_peer_cities & _UK_CITIES:
            peer_groups.append(_UK_CITIES)
        for group in peer_groups:
            for city in group:
                if city in accepted_peer_cities:
                    continue
                if " " in city:
                    if city in text_lower:
                        return False
                elif city in tokens:
                    return False

        # Accept if any configured city or its expansion appears.
        for term in accepted_terms:
            if " " in term:
                if term in text_lower:
                    return True
            elif term in tokens:
                return True
        # Final fallback: substring check for each configured filter.
        return any(filt in text_lower for filt in configured)
