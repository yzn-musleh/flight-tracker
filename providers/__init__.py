"""Provider selection: one config value (FLIGHT_PROVIDER) picks the
FlightProvider implementation the rest of the app uses. Adding a real
provider means adding a module + registering it in _PROVIDERS below -- no
changes anywhere else, per CLAUDE.md's target architecture.
"""

import os

from providers.aviationstack import AviationstackProvider
from providers.base import FlightProvider, FlightSnapshot, QuotaPolicy
from providers.fake import FakeProvider

__all__ = [
    "AviationstackProvider",
    "FakeProvider",
    "FlightProvider",
    "FlightSnapshot",
    "QuotaPolicy",
    "get_provider",
]

_PROVIDERS: dict[str, type[FlightProvider]] = {
    "aviationstack": AviationstackProvider,
    "fake": FakeProvider,
}


def get_provider(name: str | None = None) -> FlightProvider:
    name = (name or os.environ.get("FLIGHT_PROVIDER", "aviationstack")).lower()
    try:
        cls = _PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown FLIGHT_PROVIDER: {name!r}. Known providers: {sorted(_PROVIDERS)}"
        ) from None
    return cls()
