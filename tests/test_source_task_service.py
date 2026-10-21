from vimi_social.source.service import infer_requested_sources


def test_broad_intent_does_not_conflate_ui_language_with_search_source() -> None:
    assert infer_requested_sources("найди свежие видео про фитнес") == ()


def test_explicit_x_source_is_detected() -> None:
    assert infer_requested_sources("Find fresh clips on X about fitness") == ("x",)
    assert infer_requested_sources("Найди в Твиттере ролики про спорт") == ("x",)


def test_explicit_unavailable_source_is_preserved_for_fail_closed_routing() -> None:
    assert infer_requested_sources("Найди это в Telegram") == ("telegram",)
    assert infer_requested_sources("Search Reddit for this topic") == ("reddit",)
