import datetime as dt
from unittest.mock import MagicMock
import httpx
from crawlerdemo.sources.rss import crawl_rss
from crawlerdemo.sources.sitemap import crawl_sitemap
from crawlerdemo.models import ArticleIn

def test_crawl_rss(mocker):
    # Mock httpx.Client
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.content = b"""
    <rss version="2.0">
      <channel>
        <title>Test RSS</title>
        <item>
          <title>Test Title</title>
          <link>https://example.com/article</link>
          <description>Test Summary</description>
          <pubDate>Mon, 14 Apr 2026 12:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Test Title 2</title>
          <description>Missing link</description>
        </item>
      </channel>
    </rss>
    """
    mock_client.get.return_value = mock_response

    articles = list(crawl_rss(mock_client, "rss:test", "https://fake.url/rss", 10))

    assert len(articles) == 1
    assert isinstance(articles[0], ArticleIn)
    assert articles[0].title == "Test Title"
    assert articles[0].canonical_url == "https://example.com/article"
    assert articles[0].summary == "Test Summary"
    assert articles[0].source == "rss:test"


def test_crawl_sitemap_urlset(mocker):
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    # Valid sitemap urlset
    mock_response.content = b"""
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://example.com/sitemap-article</loc>
        <lastmod>2026-04-14T10:00:00Z</lastmod>
      </url>
      <url>
        <!-- missing loc tag => skipped -->
        <lastmod>2026-04-14T10:00:00Z</lastmod>
      </url>
    </urlset>
    """
    mock_client.get.return_value = mock_response

    articles = list(crawl_sitemap(mock_client, "sitemap:test", "https://fake.url/sm", 10))

    assert len(articles) == 1
    assert articles[0].canonical_url == "https://example.com/sitemap-article"
    assert articles[0].published_at == dt.datetime(2026, 4, 14, 10, 0, tzinfo=dt.timezone.utc)
    assert articles[0].source == "sitemap:test"
    assert articles[0].title is None


def test_crawl_sitemap_sitemapindex(mocker):
    mock_client = MagicMock(spec=httpx.Client)
    
    # Mock responses conditionally based on URL
    def mock_get(url):
        resp = MagicMock(spec=httpx.Response)
        if url == "https://fake.url/index.xml":
            resp.content = b"""
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <sitemap>
                    <loc>https://fake.url/child.xml</loc>
                </sitemap>
            </sitemapindex>
            """
        elif url == "https://fake.url/child.xml":
            resp.content = b"""
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url>
                    <loc>https://example.com/child-article</loc>
                </url>
            </urlset>
            """
        return resp

    mock_client.get.side_effect = mock_get

    articles = list(crawl_sitemap(mock_client, "sitemap:test", "https://fake.url/index.xml", 10))

    assert len(articles) == 1
    assert articles[0].canonical_url == "https://example.com/child-article"

