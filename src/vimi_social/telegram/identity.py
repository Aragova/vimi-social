from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.auth.context import ExecutionContext
from vimi_social.domain.identity import TenantId
from vimi_social.domain.international import (
    AgeEligibility,
    CountryCode,
    IanaTimezone,
    UiLocale,
)
from vimi_social.telegram.models import TelegramUser


@dataclass(frozen=True, slots=True)
class TelegramPrincipal:
    user_id: UUID
    context: ExecutionContext
    locale: UiLocale
    timezone: IanaTimezone
    region: CountryCode | None
    age_eligibility: AgeEligibility


class TelegramIdentityResolver:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def resolve(self, user: TelegramUser) -> TelegramPrincipal:
        with self._session_factory() as session, session.begin():
            raw_row = session.execute(
                text(
                    """
                    SELECT *
                    FROM resolve_or_create_telegram_context(
                        :telegram_user_id,
                        :username,
                        :language_code
                    )
                    """
                ),
                {
                    "telegram_user_id": user.id,
                    "username": user.username,
                    "language_code": user.language_code,
                },
            ).mappings().one()

        row = cast(Mapping[str, object], raw_row)
        user_id = _require_uuid(row["resolved_user_id"], "resolved_user_id")
        tenant_id = _require_uuid(row["resolved_tenant_id"], "resolved_tenant_id")
        locale = UiLocale(_require_str(row["resolved_locale"], "resolved_locale"))
        timezone = IanaTimezone(_require_str(row["resolved_timezone"], "resolved_timezone"))
        region_raw = row["resolved_region"]
        region = CountryCode(region_raw) if isinstance(region_raw, str) else None
        age = AgeEligibility(
            _require_str(row["resolved_age_eligibility"], "resolved_age_eligibility")
        )
        return TelegramPrincipal(
            user_id=user_id,
            context=ExecutionContext(
                tenant_id=TenantId(tenant_id),
                actor_subject=f"telegram:{user.id}",
            ),
            locale=locale,
            timezone=timezone,
            region=region,
            age_eligibility=age,
        )


def _require_uuid(value: object, name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise RuntimeError(f"{name} was not returned as a UUID")


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{name} was not returned as text")
    return value


class TelegramUpdateClaim(StrEnum):
    CLAIMED = "CLAIMED"
    BUSY = "BUSY"
    PROCESSED = "PROCESSED"


class TelegramUpdateGuard:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def claim(self, update_id: int, telegram_user_id: int | None) -> TelegramUpdateClaim:
        with self._session_factory() as session, session.begin():
            raw = session.execute(
                text("SELECT claim_telegram_update(:update_id, :telegram_user_id)"),
                {"update_id": update_id, "telegram_user_id": telegram_user_id},
            ).scalar_one()
        if not isinstance(raw, str):
            raise RuntimeError("claim_telegram_update returned a non-text result")
        return TelegramUpdateClaim(raw)

    def complete(self, update_id: int) -> None:
        with self._session_factory() as session, session.begin():
            session.execute(
                text("SELECT complete_telegram_update(:update_id)"),
                {"update_id": update_id},
            )

    def defer(self, update_id: int, retry_after_seconds: int) -> None:
        with self._session_factory() as session, session.begin():
            session.execute(
                text("SELECT defer_telegram_update(:update_id, :retry_after_seconds)"),
                {
                    "update_id": update_id,
                    "retry_after_seconds": retry_after_seconds,
                },
            )
