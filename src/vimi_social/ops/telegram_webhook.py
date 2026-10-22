import httpx


def telegram_request(
    method: str,
    token: str,
    endpoint: str,
    *,
    data: dict[str, str] | None = None,
) -> httpx.Response:
    try:
        response = httpx.request(
            method,
            f"https://api.telegram.org/bot{token}/{endpoint}",
            data=data,
            timeout=20.0,
        )
    except httpx.RequestError:
        raise RuntimeError(f"Telegram {endpoint} request failed") from None
    if response.is_error:
        raise RuntimeError(
            f"Telegram {endpoint} failed with HTTP {response.status_code}"
        )
    return response
