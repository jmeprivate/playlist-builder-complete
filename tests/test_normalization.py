from playlist_builder.normalization import deduplicate_display_values, normalize_for_search


def test_normalization_ignores_case_accents_unicode_and_spaces() -> None:
    assert normalize_for_search("  BJÖRK  Guðmundsdóttir ") == normalize_for_search(
        "bjork Guðmundsdóttir"
    )
    assert normalize_for_search("Cafe\u0301") == "cafe"


def test_deduplication_preserves_first_display_form() -> None:
    assert deduplicate_display_values([" Björk ", "bjork", "Talk   Talk"]) == (
        "Björk",
        "Talk Talk",
    )
