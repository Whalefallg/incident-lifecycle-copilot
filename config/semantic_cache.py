"""
Semantic Cache 实现 - 基于 Redis + 语义相似度

使用 sentence-transformers 计算查询的嵌入向量，
通过余弦相似度匹配缓存，减少 LLM API 调用成本。
"""

import os
import json
import logging
import hashlib
from typing import Optional, Dict, Any
from datetime import datetime

import numpy as np
from redis.asyncio import Redis
from dotenv import load_dotenv

from config.redis_config import RedisClient

load_dotenv()
logger = logging.getLogger(__name__)


class SemanticCache:
    """语义缓存 - 基于向量相似度的 LLM 响应缓存"""

    CACHE_KEY_PREFIX = "semantic_cache:"
    EMBEDDING_KEY_PREFIX = "cache_embedding:"
    STATS_KEY = "cache_stats"

    def __init__(
        self,
        enabled: Optional[bool] = None,
        threshold: Optional[float] = None,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.enabled = enabled if enabled is not None else os.getenv("SEMANTIC_CACHE_ENABLED", "false").lower() == "true"
        self.threshold = threshold if threshold is not None else float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.85"))
        self.ttl = int(os.getenv("REDIS_CACHE_TTL", "7200"))

        self._redis: Optional[Redis] = None
        self._model: Optional[Any] = None
        self._model_name = model_name

        if self.enabled:
            logger.info(f"✅ Semantic Cache enabled (threshold={self.threshold}, ttl={self.ttl}s)")
        else:
            logger.info("⚠️  Semantic Cache disabled")

    async def _get_redis(self) -> Redis:
        """获取 Redis 客户端"""
        if self._redis is None:
            self._redis = await RedisClient.get_client()
        return self._redis

    def _get_model(self):
        """获取嵌入模型（懒加载）"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
            logger.info("✅ Embedding model loaded")
        return self._model

    def _compute_embedding(self, text: str) -> np.ndarray:
        """计算文本嵌入"""
        model = self._get_model()
        embedding = model.encode(text, convert_to_numpy=True)
        return embedding

    def _cosine_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """计算余弦相似度"""
        return float(np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2)))

    def _context_namespace(self, context: Optional[Dict[str, Any]] = None) -> str:
        if not context:
            return "global"
        serialised = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]

    def _generate_cache_key(
        self, query: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """生成缓存键"""
        query_hash = hashlib.sha256(query.encode()).hexdigest()
        return f"{self.CACHE_KEY_PREFIX}{self._context_namespace(context)}:{query_hash}"

    async def get(
        self, query: str, context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """从缓存中获取响应"""
        if not self.enabled:
            return None

        try:
            redis = await self._get_redis()

            # 计算查询的嵌入
            query_embedding = self._compute_embedding(query)

            # 获取所有缓存的嵌入键
            namespace = self._context_namespace(context)
            embedding_keys = await redis.keys(
                f"{self.EMBEDDING_KEY_PREFIX}{namespace}:*"
            )

            if not embedding_keys:
                await self._record_stats("miss")
                return None

            # 查找最相似的缓存项
            best_similarity = 0.0
            best_key = None

            for emb_key in embedding_keys:
                cached_emb_str = await redis.get(emb_key)
                if not cached_emb_str:
                    continue

                cached_emb = np.array(json.loads(cached_emb_str))
                similarity = self._cosine_similarity(query_embedding, cached_emb)

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_key = emb_key

            # 如果相似度超过阈值，返回缓存
            if best_similarity >= self.threshold and best_key:
                cache_key = best_key.replace(self.EMBEDDING_KEY_PREFIX, self.CACHE_KEY_PREFIX)
                cached_response = await redis.get(cache_key)

                if cached_response:
                    await self._record_stats("hit")
                    logger.debug(f"✅ Cache HIT (similarity={best_similarity:.3f})")
                    return cached_response

            await self._record_stats("miss")
            logger.debug(f"❌ Cache MISS (best_similarity={best_similarity:.3f})")
            return None

        except Exception as e:
            logger.error(f"Cache get error: {e}")
            await self._record_stats("miss")
            return None

    async def set(
        self,
        query: str,
        response: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """将响应存入缓存"""
        if not self.enabled:
            return False

        try:
            redis = await self._get_redis()

            # 计算查询的嵌入
            query_embedding = self._compute_embedding(query)

            # 生成键
            cache_key = self._generate_cache_key(query, context)
            embedding_key = cache_key.replace(self.CACHE_KEY_PREFIX, self.EMBEDDING_KEY_PREFIX)

            # 存储响应和嵌入
            embedding_json = json.dumps(query_embedding.tolist())

            await redis.setex(cache_key, self.ttl, response)
            await redis.setex(embedding_key, self.ttl, embedding_json)

            logger.debug(f"✅ Cached response (TTL={self.ttl}s)")
            return True

        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False

    async def _record_stats(self, result: str):
        """记录统计信息"""
        try:
            redis = await self._get_redis()
            await redis.hincrby(self.STATS_KEY, result, 1)
        except Exception as e:
            logger.error(f"Failed to record stats: {e}")

    async def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            redis = await self._get_redis()
            stats_data = await redis.hgetall(self.STATS_KEY)

            hits = int(stats_data.get("hit", 0))
            misses = int(stats_data.get("miss", 0))
            total = hits + misses
            hit_rate = (hits / total * 100) if total > 0 else 0.0

            return {
                "enabled": self.enabled,
                "hits": hits,
                "misses": misses,
                "total_queries": total,
                "hit_rate_percent": round(hit_rate, 2),
                "threshold": self.threshold,
                "ttl": self.ttl,
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {
                "enabled": self.enabled,
                "error": str(e),
            }

    async def clear(self) -> bool:
        """清空缓存"""
        try:
            redis = await self._get_redis()

            cache_keys = await redis.keys(f"{self.CACHE_KEY_PREFIX}*")
            embedding_keys = await redis.keys(f"{self.EMBEDDING_KEY_PREFIX}*")

            all_keys = cache_keys + embedding_keys + [self.STATS_KEY]

            if all_keys:
                await redis.delete(*all_keys)

            logger.info(f"✅ Cache cleared ({len(all_keys)} keys deleted)")
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False


# 全局实例
semantic_cache = SemanticCache()
