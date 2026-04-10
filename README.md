# CrawlerDemo

A simple crawler that pulls public/free data sources (RSS + sitemap), stores results in a database,
runs in Docker, and deploys to EC2 via GitHub Actions.

### What sources does it crawl?

Defaults:
- **RSS**:
  - `https://www.state.gov/rss/channels/prsreleases.xml` (US State Dept – Press Releases)
  - `https://www.state.gov/rss/channels/briefings.xml` (US State Dept – Briefings)
  - `https://www.state.gov/rss/channels/remarks.xml` (US State Dept – Remarks)
  - `https://congbao.chinhphu.vn/cac-van-ban-moi-ban-hanh.rss` (Vietnam Government Gazette – New documents)
- **Sitemap**:
  - `https://www.theguardian.com/sitemaps/news.xml`
  - `https://en.baochinhphu.vn/sitemap.xml` (Vietnam Government News – English, best-effort)

You can override sources with environment variables (JSON lists):
- **`CRAWLER_RSS_URLS`**:
  - `CRAWLER_RSS_URLS='["https://feeds.reuters.com/Reuters/worldNews"]'`
  - `CRAWLER_RSS_URLS='["https://vietstock.vn/rss/chung-khoan-1.rss"]'`
- **`CRAWLER_SITEMAP_URLS`**:
  - `CRAWLER_SITEMAP_URLS='["https://example.com/sitemap.xml"]'`

### Project layout

- `src/crawlerdemo/`: crawler source code
  - `config.py`: environment-based config (`CRAWLER_*`)
  - `db.py`: `Article` model + SQLite/Postgres via SQLAlchemy
  - `sources/rss.py`: RSS crawl
  - `sources/sitemap.py`: sitemap crawl (urlset + sitemapindex)
  - `worker.py`: scheduled worker (APScheduler)
  - `cli.py`: CLI (`crawl-once`, `worker`, `recent`)
- `Dockerfile`: worker image
- `docker-compose.yml`: local run
- `docker-compose.ec2.yml`: EC2 run (image from registry)
- `.github/workflows/deploy.yml`: build/push (Docker Hub) + EC2 deploy

### Deploy to EC2 (end-to-end)

1. **Prepare EC2**
   - Ubuntu 22.04+, security group allows SSH (22).
   - Install Docker + Docker Compose plugin.
   - Allow inbound **8090** to access the web service.

2. **Add GitHub Actions secrets**
   In your GitHub repo, create **Repository secrets**:
   - `EC2_HOST`: public DNS/IP EC2
   - `EC2_USER`: SSH user (usually `ubuntu`)
   - `EC2_SSH_KEY`: private key (PEM/OpenSSH) for EC2 login
   - `EC2_APP_DIR`: remote app directory, e.g. `/opt/crawlerdemo`
   - `DOCKERHUB_USERNAME`: `duyhung81002`
   - `DOCKERHUB_TOKEN`: Docker Hub access token (Account Settings → Security → New Access Token)

3. **Workflow**
   - On every push to `main`:
     - Build Docker image and push to **Docker Hub** tags:
       - `duyhung81002/crawler_test:<git_sha>` (immutable)
       - `duyhung81002/crawler_test:latest` (moving tag)
     - SSH into EC2:
       - create/update `docker-compose.ec2.yml` under `EC2_APP_DIR`
       - `docker pull` and `docker compose up -d`
     - If deploy succeeds, CI promotes the deployed digest to:
       - `duyhung81002/crawler_test:stable`

### Rollback

If a deploy fails, redeploy the previous stable image:

```bash
IMAGE="duyhung81002/crawler_test:stable"
```

After deploy, access:
- `http://<EC2_PUBLIC_IP>:8090/`
- `http://<EC2_PUBLIC_IP>:8090/api/articles?limit=50`

Web UI now supports:
- reload/filter article list
- trigger manual crawl from browser (`POST /api/crawl`)
- monitor crawler status (`GET /api/crawl-status`)
- list/search configured sources to guide end users (`GET /api/sources`)

After a successful deploy, on EC2 you can check:

```bash
cd /opt/crawlerdemo   # or your configured directory
docker compose -f docker-compose.ec2.yml ps
docker compose -f docker-compose.ec2.yml logs -f
```
