import json
from unittest.mock import MagicMock
from crawlerdemo.export import export_csv, export_json, upload_to_s3
from crawlerdemo.db import Article

def test_export_csv():
    articles = [
        Article(id=1, source="test", title="csv_title", canonical_url="http://u", published_at=None, fetched_at=None),
        Article(id=2, source="test", title='title "with" quotes', canonical_url="http://u2", published_at=None, fetched_at=None),
    ]
    
    csv_bytes = export_csv(articles)
    assert isinstance(csv_bytes, bytes)
    
    csv_str = csv_bytes.decode("utf-8")
    lines = csv_str.strip().split("\r\n")
    assert len(lines) == 3
    assert "id,source,title" in lines[0]
    assert "csv_title" in lines[1]
    assert 'title ""with"" quotes' in lines[2]

def test_export_json():
    articles = [
        Article(id=1, source="test", title="json_title", canonical_url="http://u", summary="sum", published_at=None, fetched_at=None),
    ]
    
    json_bytes = export_json(articles)
    assert isinstance(json_bytes, bytes)
    
    data = json.loads(json_bytes.decode("utf-8"))
    assert len(data) == 1
    assert data[0]["title"] == "json_title"
    assert data[0]["source"] == "test"

def test_upload_to_s3(mocker):
    # Mock boto3 client
    mock_boto3 = mocker.patch("crawlerdemo.export.boto3.client")
    mock_client = MagicMock()
    mock_boto3.return_value = mock_client
    
    data = b"testdata"
    
    key = upload_to_s3(
        data=data,
        bucket="test-bucket",
        prefix="dev/",
        fmt="csv",
        region="us-east-1",
        content_type="text/csv"
    )
    
    assert key.startswith("dev/")
    assert key.endswith(".csv")
    
    mock_client.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key=key,
        Body=data,
        ContentType="text/csv",
        ContentDisposition='attachment; filename="articles.csv"'
    )
