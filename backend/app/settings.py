import math
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    freshness_max_age_hours: float = 36
    max_availability_limit: int = 100
    request_timeout_seconds: float = 15
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.freshness_max_age_hours) or self.freshness_max_age_hours <= 0:
            raise ValueError("FRESHNESS_MAX_AGE_HOURS must be positive and finite")
        if not 1 <= self.max_availability_limit <= 100:
            raise ValueError("MAX_AVAILABILITY_LIMIT must be between 1 and 100")
        if not math.isfinite(self.request_timeout_seconds) or self.request_timeout_seconds <= 3:
            raise ValueError(
                "API_REQUEST_TIMEOUT_SECONDS must exceed the database statement timeout"
            )
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or "*" in origin
            ):
                raise ValueError("ALLOWED_ORIGINS must contain exact HTTP(S) origins")

    @classmethod
    def from_environment(cls) -> "Settings":
        try:
            return cls(
                freshness_max_age_hours=float(os.getenv("FRESHNESS_MAX_AGE_HOURS", "36")),
                max_availability_limit=int(os.getenv("MAX_AVAILABILITY_LIMIT", "100")),
                request_timeout_seconds=float(os.getenv("API_REQUEST_TIMEOUT_SECONDS", "15")),
                allowed_origins=tuple(
                    origin.strip()
                    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
                    if origin.strip()
                ),
            )
        except ValueError:
            raise ValueError("Invalid API environment configuration") from None
