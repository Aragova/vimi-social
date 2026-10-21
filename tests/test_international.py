from decimal import Decimal

import pytest

from vimi_social.domain.international import (
    CountryCode,
    CurrencyCode,
    IanaTimezone,
    Money,
    UiLocale,
    ui_locale_from_telegram,
)


def test_telegram_language_is_only_an_initial_ru_en_hint() -> None:
    assert ui_locale_from_telegram("ru") is UiLocale.RU
    assert ui_locale_from_telegram("ru-RU") is UiLocale.RU
    assert ui_locale_from_telegram("en") is UiLocale.EN
    assert ui_locale_from_telegram("de") is UiLocale.EN
    assert ui_locale_from_telegram(None) is UiLocale.EN


def test_timezone_country_and_currency_are_structured_types() -> None:
    assert IanaTimezone("Europe/Moscow").value == "Europe/Moscow"
    assert CountryCode("us").value == "US"
    assert CurrencyCode("usd").value == "USD"
    assert Money(Decimal("9.99"), CurrencyCode("USD")).amount == Decimal("9.99")

    with pytest.raises(ValueError):
        IanaTimezone("Not/A-Timezone")
    with pytest.raises(ValueError):
        CountryCode("USA")
    with pytest.raises(ValueError):
        CurrencyCode("US")
