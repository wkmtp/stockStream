"""ORM 数据模型 — 所有持久化表定义。

表清单:
    stock_prices    — 股票实时价格
    trade_records   — 交易记录
    live_sessions   — 直播场次
    live_segments   — 直播节目段
    danmu_records   — 弹幕记录
    gift_records    — 礼物记录
    follower_snapshots — 粉丝快照
    schema_version  — Schema 迁移版本
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, func
from src.storage.service import Base


class StockPrice(Base):
    __tablename__ = "stock_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), nullable=False, index=True)
    price = Column(Float, nullable=False)
    volume = Column(Integer, default=0)
    timestamp = Column(String(32), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class TradeRecord(Base):
    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), nullable=False, index=True)
    action = Column(String(16), nullable=False)
    quantity = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, default=0.0)
    reason = Column(Text, default="")
    timestamp = Column(String(32), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class LiveSession(Base):
    __tablename__ = "live_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(32), nullable=False, index=True)
    room_id = Column(String(64), nullable=False)
    status = Column(String(16), default="live")
    started_at = Column(String(32), nullable=False)
    ended_at = Column(String(32), nullable=True)
    peak_viewers = Column(Integer, default=0)
    total_likes = Column(Integer, default=0)
    total_gifts = Column(Integer, default=0)
    total_comments = Column(Integer, default=0)
    total_followers = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())


class LiveSegment(Base):
    __tablename__ = "live_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, nullable=False, index=True)
    segment_type = Column(String(32), nullable=False)
    content = Column(Text, default="")
    duration = Column(Float, default=0.0)
    timestamp = Column(String(32), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class DanmuRecord(Base):
    __tablename__ = "danmu_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(32), nullable=False, index=True)
    username = Column(String(64), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(128), default="")
    user_level = Column(Integer, default=0)
    session_id = Column(Integer, default=0)
    timestamp = Column(String(32), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class GiftRecord(Base):
    __tablename__ = "gift_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(32), nullable=False, index=True)
    username = Column(String(64), nullable=False)
    gift_name = Column(String(64), nullable=False)
    value = Column(Float, default=0.0)
    count = Column(Integer, default=1)
    session_id = Column(Integer, default=0)
    timestamp = Column(String(32), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class FollowerSnapshot(Base):
    __tablename__ = "follower_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(32), nullable=False, index=True)
    follower_count = Column(Integer, nullable=False)
    timestamp = Column(String(32), nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(16), nullable=False)
    applied_at = Column(DateTime, server_default=func.now())
    description = Column(Text, default="")
