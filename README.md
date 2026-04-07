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
   - You only need inbound SSH (22). The web service is bound to `127.0.0.1:8090` and should be exposed via Nginx.

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
     - Build Docker image and push to **Docker Hub** (`duyhung81002/crawler_test:latest`).
     - SSH into EC2:
       - create/update `docker-compose.ec2.yml` under `EC2_APP_DIR`
       - `docker pull` and `docker compose up -d`

After deploy, the web service listens on **127.0.0.1:8090** (for reverse proxy via Nginx):
- `http://127.0.0.1:8090/`
- `http://127.0.0.1:8090/api/articles?limit=50`

After a successful deploy, on EC2 you can check:

```bash
cd /opt/crawlerdemo   # or your configured directory
docker compose -f docker-compose.ec2.yml ps
docker compose -f docker-compose.ec2.yml logs -f
```
