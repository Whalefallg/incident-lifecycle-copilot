"""
Redis 配置与连接管理

支持:
- Agent 状态机共享存储
- Semantic Cache 存储
- 分布式会话管理
"""

import os
import json
import logging
from typing import Any, Optional
from datetime import timedelta

import redis.asyncio as aioredis
from redis.asyncio import Redis
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class RedisConfig:
    """Redis 连接配置"""

    def __init__(self):
        self.host = os.getenv("REDIS_HOST", "localhost")
        self.port = int(os.getenv("REDIS_PORT", "6379"))
        self.db = int(os.getenv("REDIS_DB", "0"))
        self.password = os.getenv("REDIS_PASSWORD")
        self.max_connections = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
        self.socket_timeout = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
        self.socket_connect_timeout = int(os.getenv("REDIS_CONNECT_TIMEOUT", "5"))

        self.state_ttl = int(os.getenv("REDIS_STATE_TTL", "3600"))
        self.cache_ttl = int(os.getenv("REDIS_CACHE_TTL", "7200"))

    def get_connection_kwargs(self) -> dict:
        """获取 Redis 连接参数"""
        kwargs = {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "decode_responses": True,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
        }
        if self.password:
            kwargs["password"] = self.password
        return kwargs


class RedisClient:
    """Redis 客户端单例"""

    _instance: Optional[Redis] = None
    _config: Optional[RedisConfig] = None

    @classmethod
    async def get_client(cls) -> Redis:
        """获取 Redis 客户端实例（单例模式）"""
        if cls._instance is None:
            cls._config = RedisConfig()
            cls._instance = await aioredis.from_url(
                f"redis://{cls._config.host}:{cls._config.port}/{cls._config.db}",
                password=cls._config.password,
                decode_responses=True,
                max_connections=cls._config.max_connections,
            )
            logger.info(
                f"✅ Redis connected: {cls._config.host}:{cls._config.port}/{cls._config.db}"
            )
        return cls._instance

    @classmethod
    async def close(cls):
        """关闭 Redis 连接"""
        if cls._instance:
            await cls._instance.close()
            cls._instance = None
            logger.info("Redis connection closed")

    @classmethod
    def get_config(cls) -> RedisConfig:
        """获取配置实例"""
        if cls._config is None:
            cls._config = RedisConfig()
        return cls._config
