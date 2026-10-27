import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.identity import TenantId
from vimi_social.domain.interest import UserInterestProfile
from vimi_social.source.interest_profile import InterestProfileDraft


class UserInterestProfileRepository:
    def get(
        self,
        session: Session,
        *,
        user_id: UUID,
    ) -> UserInterestProfile | None:
        row = session.execute(
            text(
                """
                SELECT tenant_id, user_id, destination_account_id, external_account_id,
                       term_weights, hashtag_weights, author_weights, source_stats,
                       sample_size, generated_at
                FROM x_user_interest_profile
                WHERE user_id = :user_id
                """
            ),
            {"user_id": str(user_id)},
        ).mappings().one_or_none()
        if row is None:
            return None
        mapped = cast(Mapping[str, object], row)
        return UserInterestProfile(
            tenant_id=TenantId.parse(str(mapped["tenant_id"])),
            user_id=_uuid(mapped["user_id"], "profile user id"),
            destination_account_id=_uuid(
                mapped["destination_account_id"],
                "profile destination account id",
            ),
            external_account_id=str(mapped["external_account_id"]),
            term_weights=_float_mapping(mapped["term_weights"]),
            hashtag_weights=_float_mapping(mapped["hashtag_weights"]),
            author_weights=_float_mapping(mapped["author_weights"]),
            source_stats=_int_mapping(mapped["source_stats"]),
            sample_size=int(mapped["sample_size"]),
            generated_at=_datetime(mapped["generated_at"]),
        )

    def upsert(
        self,
        session: Session,
        *,
        tenant_id: TenantId,
        user_id: UUID,
        destination_account_id: UUID,
        external_account_id: str,
        draft: InterestProfileDraft,
    ) -> UserInterestProfile:
        row = session.execute(
            text(
                """
                INSERT INTO x_user_interest_profile (
                    tenant_id, user_id, destination_account_id, external_account_id,
                    term_weights, hashtag_weights, author_weights, source_stats,
                    sample_size, generated_at, updated_at
                ) VALUES (
                    :tenant_id, :user_id, :destination_account_id, :external_account_id,
                    CAST(:term_weights AS jsonb), CAST(:hashtag_weights AS jsonb),
                    CAST(:author_weights AS jsonb), CAST(:source_stats AS jsonb),
                    :sample_size, clock_timestamp(), clock_timestamp()
                )
                ON CONFLICT (tenant_id, user_id) DO UPDATE
                SET destination_account_id = EXCLUDED.destination_account_id,
                    external_account_id = EXCLUDED.external_account_id,
                    term_weights = EXCLUDED.term_weights,
                    hashtag_weights = EXCLUDED.hashtag_weights,
                    author_weights = EXCLUDED.author_weights,
                    source_stats = EXCLUDED.source_stats,
                    sample_size = EXCLUDED.sample_size,
                    generated_at = clock_timestamp(),
                    updated_at = clock_timestamp()
                RETURNING tenant_id, user_id, destination_account_id, external_account_id,
                          term_weights, hashtag_weights, author_weights, source_stats,
                          sample_size, generated_at
                """
            ),
            {
                "tenant_id": str(tenant_id.value),
                "user_id": str(user_id),
                "destination_account_id": str(destination_account_id),
                "external_account_id": external_account_id,
                "term_weights": json.dumps(draft.term_weights, separators=(",", ":")),
                "hashtag_weights": json.dumps(
                    draft.hashtag_weights,
                    separators=(",", ":"),
                ),
                "author_weights": json.dumps(
                    draft.author_weights,
                    separators=(",", ":"),
                ),
                "source_stats": json.dumps(draft.source_stats, separators=(",", ":")),
                "sample_size": draft.sample_size,
            },
        ).mappings().one()
        mapped = cast(Mapping[str, object], row)
        return UserInterestProfile(
            tenant_id=TenantId.parse(str(mapped["tenant_id"])),
            user_id=_uuid(mapped["user_id"], "profile user id"),
            destination_account_id=_uuid(
                mapped["destination_account_id"],
                "profile destination account id",
            ),
            external_account_id=str(mapped["external_account_id"]),
            term_weights=_float_mapping(mapped["term_weights"]),
            hashtag_weights=_float_mapping(mapped["hashtag_weights"]),
            author_weights=_float_mapping(mapped["author_weights"]),
            source_stats=_int_mapping(mapped["source_stats"]),
            sample_size=int(mapped["sample_size"]),
            generated_at=_datetime(mapped["generated_at"]),
        )


def _float_mapping(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, float] = {}
    for key, raw in cast(dict[object, object], value).items():
        if isinstance(key, str) and isinstance(raw, int | float) and not isinstance(raw, bool):
            result[key] = max(0.0, min(1.0, float(raw)))
    return result


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw in cast(dict[object, object], value).items():
        if isinstance(key, str) and isinstance(raw, int) and not isinstance(raw, bool):
            result[key] = max(0, raw)
    return result


def _uuid(value: object, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise RuntimeError(f"invalid {label}") from exc


def _datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    raise RuntimeError("invalid profile generated_at")
