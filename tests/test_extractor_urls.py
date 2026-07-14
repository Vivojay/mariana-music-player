from mariana.extractor_urls import extractor_key_for_url, has_dedicated_extractor


def test_installed_ytdlp_registry_recognizes_non_youtube_media_pages():
    assert extractor_key_for_url("https://soundcloud.com/artist/track") == "Soundcloud"
    assert extractor_key_for_url("https://www.dailymotion.com/video/x9abc") == "Dailymotion"
    assert has_dedicated_extractor("https://vimeo.com/123456")


def test_extractor_classification_preserves_direct_and_credentialed_url_safety():
    assert not has_dedicated_extractor("https://media.example.test/song.mp3")
    assert not has_dedicated_extractor("https://user:password@soundcloud.com/artist/track")
    assert not has_dedicated_extractor("file:///private/song.mp3")
