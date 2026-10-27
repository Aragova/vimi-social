import pytest

from vimi_social.source.query_planner import MultilingualQueryPlanner


class FakeTranslator:
    async def translate_to_english(self, intent: str) -> str | None:
        assert intent == "Гей порно твинк молодые"
        return "Gay porn twink young"


@pytest.mark.asyncio
async def test_broad_or_rounds_are_page_capped_but_anchor_fallback_is_not() -> None:
    planner = MultilingualQueryPlanner(FakeTranslator())
    intent = "Гей порно твинк молодые"
    plan = await planner.plan(intent, ("ru", "en"))

    rounds = [
        item async for item in planner.search_rounds(plan, intent, ("ru", "en"))
    ]

    assert [item.query_variants for item in rounds] == [
        ("Гей", "порно", "твинк", "молодые"),
        ("Gay", "porn", "twink", "young"),
        ("Gay", "porn", "twink", "young"),
        ("twink",),
    ]
    assert [item.max_pages for item in rounds] == [2, 2, 2, None]
