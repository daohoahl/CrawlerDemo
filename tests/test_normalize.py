"""Unit tests for crawlerdemo.normalize.canonicalize_url."""

from crawlerdemo.normalize import canonicalize_url


def test_strips_fragment():
    assert (
        canonicalize_url("https://example.com/path#section")
        == "https://example.com/path"
    )


def test_strips_trailing_slash():
    assert canonicalize_url("https://example.com/path/") == "https://example.com/path"


def test_sorts_query_params_alphabetically():
    # 'z' before 'a' on input → 'a' before 'z' on output
    assert (
        canonicalize_url("https://example.com/path?z=2&a=1")
        == "https://example.com/path?a=1&z=2"
    )


def test_sorts_and_strips_together():
    # Combined normalisation should match the spec's dedup-first behaviour
    left = canonicalize_url("https://example.com/x/?b=2&a=1#frag")
    right = canonicalize_url("https://example.com/x?a=1&b=2")
    assert left == right


def test_keeps_root_path_as_slash():
    assert canonicalize_url("https://example.com/") == "https://example.com/"


def test_preserves_empty_query_values():
    # keep_blank_values=True so flag-style params are not silently dropped
    assert (
        canonicalize_url("https://example.com/path?flag=&x=1")
        == "https://example.com/path?flag=&x=1"
    )
