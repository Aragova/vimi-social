from vimi_social.domain.international import UiLocale
from vimi_social.i18n.publication import PublicationMessageKey, translate_publication


def test_every_publication_message_key_resolves_for_every_supported_locale() -> None:
    for locale in UiLocale:
        for key in PublicationMessageKey:
            assert translate_publication(key, locale).strip()
