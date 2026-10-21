import pytest

from vimi_social.domain.identity import OperationKey


def test_operation_key_is_trimmed_and_stable() -> None:
    assert OperationKey("  op-123  ").value == "op-123"


def test_operation_key_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        OperationKey("   ")


def test_operation_key_rejects_oversized_value() -> None:
    with pytest.raises(ValueError, match="exceeds 200"):
        OperationKey("x" * 201)
