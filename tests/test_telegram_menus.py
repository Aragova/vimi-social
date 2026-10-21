from vimi_social.domain.international import UiLocale
from vimi_social.telegram.menus import build_main_menu, build_source_menu


def test_main_menu_is_localized_without_changing_callback_contract() -> None:
    ru = build_main_menu(UiLocale.RU)
    en = build_main_menu(UiLocale.EN)

    assert "Добро пожаловать" in ru.text
    assert "Welcome" in en.text
    assert ru.keyboard[0][0].callback_data == "task:new"
    assert en.keyboard[0][0].callback_data == "task:new"


def test_source_menu_exposes_all_three_canonical_source_modes() -> None:
    menu = build_source_menu(UiLocale.RU)
    callbacks = [row[0].callback_data for row in menu.keyboard]
    assert callbacks == ["source:ai_search", "source:manual_upload", "source:feed"]
