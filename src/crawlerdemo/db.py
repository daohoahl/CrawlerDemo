from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(512))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), index=True
    )


@dataclass(frozen=True)
class ArticleIn:
    source: str
    canonical_url: str
    title: str | None = None
    summary: str | None = None
    published_at: dt.datetime | None = None


def make_engine(database_url: str):
    # SQLite needs check_same_thread=False when used across threads; safe here either way.
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def upsert_articles(session: Session, items: Iterable[ArticleIn]) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for it in items:
        existing = session.scalar(select(Article).where(Article.canonical_url == it.canonical_url))
        if existing:
            skipped += 1
            continue
        session.add(
            Article(
                source=it.source,
                canonical_url=it.canonical_url,
                title=it.title,
                summary=it.summary,
                published_at=it.published_at,
            )
        )
        inserted += 1
    session.commit()
    return inserted, skipped


def list_recent(session: Session, limit: int = 50) -> list[Article]:
    stmt = select(Article).order_by(Article.fetched_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())

