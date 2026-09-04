import httpx

from app.services.extractor.gemini_client import (
    classify_google_error,
    get_retry_after,
)


def make_response(status_code: int, payload: dict, headers: dict | None = None):
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request("POST", "https://example.test"),
    )


def test_quota_error_is_reduced_to_stable_reason():
    response = make_response(
        429,
        {
            "error": {
                "message": "You exceeded your current quota.\nPlease retry in 48.04s.",
                "details": [],
            }
        },
    )

    assert classify_google_error(response) == "quota_exceeded"
    assert get_retry_after(response) == "48.04s"


def test_retry_after_header_has_priority():
    response = make_response(
        429,
        {"error": {"message": "Rate limited", "details": []}},
        headers={"Retry-After": "30"},
    )

    assert classify_google_error(response) == "rate_limited"
    assert get_retry_after(response) == "30"


def test_retry_delay_is_read_from_google_details():
    response = make_response(
        429,
        {
            "error": {
                "message": "Quota exceeded",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "12s",
                    }
                ],
            }
        },
    )

    assert get_retry_after(response) == "12s"
