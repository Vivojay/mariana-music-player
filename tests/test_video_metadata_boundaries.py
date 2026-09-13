import pytest

from beta.youtube_media import provider_metadata


@pytest.mark.parametrize("field", ["timestamp", "release_timestamp", "upload_date", "release_date"])
@pytest.mark.parametrize("value", [10**5000, -(10**5000)], ids=["large-positive", "large-negative"])
def test_unrepresentable_provider_publication_is_omitted_without_losing_identity(field, value):
    metadata = provider_metadata({"id": "abcdefghijk", "channel": "Publisher", field: value})
    assert metadata["provider_media_id"] == "abcdefghijk"
    assert metadata["publisher"] == "Publisher"
    assert "published" not in metadata


def test_unrepresentable_preferred_publication_falls_back_to_valid_upload_date():
    metadata = provider_metadata({"release_timestamp": 10**5000, "timestamp": float("nan"),
                                  "release_date": 10**5000, "upload_date": "20260913"})
    assert metadata["published"] == "2026-09-13"
