import argparse
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.base import build_engine
from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import TenantId
from vimi_social.publication.repository import PublicationRepository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision one user-bound X destination account for a staging tenant."
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--user-id", required=True, help="Workspace user who connected this X account.")
    parser.add_argument("--external-account-id", default="staging-primary")
    parser.add_argument("--display-name", default="Staging X")
    parser.add_argument(
        "--credential-ref",
        default="env:VIMI_DEST_X_PRIMARY_TOKEN",
        help="Secret reference only; never pass the token value here.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    tenant_id = TenantId.parse(args.tenant_id)
    connected_user_id = UUID(args.user_id)
    engine = build_engine()
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    repository = PublicationRepository()
    try:
        with session_factory() as session, tenant_transaction(session, tenant_id):
            account = repository.upsert_account(
                session,
                tenant_id=tenant_id.value,
                platform="x",
                external_account_id=args.external_account_id,
                display_name=args.display_name,
                credential_ref=args.credential_ref,
            )
            session.execute(
                text(
                    """
                    UPDATE destination_account
                    SET connected_user_id = :user_id,
                        updated_at = clock_timestamp()
                    WHERE id = :account_id
                    """
                ),
                {
                    "user_id": str(connected_user_id),
                    "account_id": str(account.id),
                },
            )
        print(
            "Provisioned X destination "
            f"id={account.id} tenant={tenant_id.value} user={connected_user_id} "
            f"credential_ref={account.credential_ref}"
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
