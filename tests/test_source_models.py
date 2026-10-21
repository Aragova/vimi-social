import pytest

from vimi_social.source.models import SourcePlatform, SourceSearchRequest


def test_source_search_request_normalizes_query() -> None:
    request = SourceSearchRequest(SourcePlatform.X, "  cats  ", 10)
    assert request.query == "cats"


def test_source_search_request_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError):
        SourceSearchRequest(SourcePlatform.X, "cats", 9)
