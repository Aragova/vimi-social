from uuid import uuid4

from vimi_social.domain.international import UiLocale
from vimi_social.domain.media import (
    BaseAdultClassification,
    MediaPreparationResult,
    MediaPreparationState,
)
from vimi_social.domain.publication import (
    PublicationPreviewResult,
    PublicationPreviewState,
)
from vimi_social.i18n.publication import PublicationMessageKey, translate_publication
from vimi_social.telegram.menus import build_media_preparation_result


def test_every_publication_message_key_resolves_for_every_supported_locale() -> None:
    for locale in UiLocale:
        for key in PublicationMessageKey:
            assert translate_publication(key, locale).strip()


def test_oversized_preview_falls_back_to_text_without_losing_publish_button() -> None:
    publication_id = uuid4()
    result = MediaPreparationResult(
        preparation_id=str(uuid4()),
        state=MediaPreparationState.READY,
        asset_id=str(uuid4()),
        sha256="a" * 64,
        size_bytes=60 * 1024 * 1024,
        duration_ms=30_000,
        width=1080,
        height=1920,
        adult_classification=BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED,
    )
    preview = PublicationPreviewResult(
        state=PublicationPreviewState.AWAITING_APPROVAL,
        artifact_id=str(uuid4()),
        publication_id=str(publication_id),
        destination="x",
        destination_name="Primary X",
    )

    message = build_media_preparation_result(
        UiLocale.EN,
        result,
        preview=preview,
        video_preview_available=False,
    )

    assert "above the safe Telegram preview limit" in message.text
    assert message.keyboard[0][0].callback_data == f"publication:approve:{publication_id}"
