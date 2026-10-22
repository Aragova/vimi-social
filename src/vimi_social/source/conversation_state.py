from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.identity import TenantId


def consume_ai_search_conversation(
    session: Session,
    *,
    tenant_id: TenantId,
    user_id: UUID,
    chat_id: int,
) -> bool:
    """Atomically consume one pending AI Search prompt.

    DELETE ... RETURNING serializes competing consumers on the same conversation
    row. Only the transaction that actually deletes the pending state may create
    and charge a new SourceTask. If the surrounding transaction rolls back, the
    pending prompt is restored automatically.
    """

    consumed = session.execute(
        text(
            """
            DELETE FROM telegram_conversation_state
            WHERE tenant_id = :tenant_id
              AND user_id = :user_id
              AND chat_id = :chat_id
              AND state = 'AWAITING_AI_SEARCH_INTENT'
            RETURNING 1
            """
        ),
        {
            "tenant_id": str(tenant_id.value),
            "user_id": str(user_id),
            "chat_id": chat_id,
        },
    ).scalar_one_or_none()
    return consumed == 1
