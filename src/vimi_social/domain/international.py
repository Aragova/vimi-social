from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class UiLocale(StrEnum):
    RU = "ru"
    EN = "en"


class AgeEligibility(StrEnum):
    UNKNOWN = "UNKNOWN"
    DECLARED_18_PLUS = "DECLARED_18_PLUS"
    VERIFIED_18_PLUS = "VERIFIED_18_PLUS"
    RESTRICTED = "RESTRICTED"


def ui_locale_from_telegram(language_code: str | None) -> UiLocale:
    if language_code is not None and language_code.lower().startswith("ru"):
        return UiLocale.RU
    return UiLocale.EN


@dataclass(frozen=True, slots=True)
class IanaTimezone:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("timezone must not be empty")
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {normalized}") from exc
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class CountryCode:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper()
        if len(normalized) != 2 or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("country code must be a two-letter ISO-style code")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class CurrencyCode:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper()
        if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("currency code must be a three-letter ISO 4217-style code")
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: CurrencyCode

    def __post_init__(self) -> None:
        if not self.amount.is_finite():
            raise ValueError("money amount must be finite")
