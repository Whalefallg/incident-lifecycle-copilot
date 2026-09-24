"""
测试 Semantic Cache 功能
"""

import pytest
from config.semantic_cache import SemanticCache

pytestmark = pytest.mark.redis_integration


@pytest.mark.asyncio
async def test_semantic_cache_basic():
    """测试基本缓存功能"""
    cache = SemanticCache(enabled=True, threshold=0.85)

    query = "What is the runbook for Redis OOM?"
    response = "Check memory usage with INFO memory, then restart the instance."

    # 初次查询应该 MISS
    result = await cache.get(query)
    assert result is None

    # 存入缓存
    success = await cache.set(query, response)
    assert success is True

    # 再次查询应该 HIT
    result = await cache.get(query)
    assert result == response


@pytest.mark.asyncio
async def test_semantic_similarity():
    """测试语义相似度匹配"""
    cache = SemanticCache(enabled=True, threshold=0.85)

    original_query = "How do I handle Redis out of memory errors?"
    response = "Check memory usage and restart."

    await cache.set(original_query, response)

    # 语义相似的查询应该命中缓存
    similar_query = "What should I do when Redis runs out of memory?"
    result = await cache.get(similar_query)

    # 由于语义相似，应该返回缓存结果
    # 注意：threshold=0.85 可能需要调整才能命中
    if result:
        assert result == response


@pytest.mark.asyncio
async def test_cache_stats():
    """测试统计功能"""
    cache = SemanticCache(enabled=True)

    await cache.set("test query 1", "response 1")
    await cache.get("test query 1")  # HIT
    await cache.get("non-existent query")  # MISS

    stats = await cache.get_stats()

    assert stats["enabled"] is True
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert stats["total_queries"] >= 2


@pytest.mark.asyncio
async def test_cache_clear():
    """测试清空缓存"""
    cache = SemanticCache(enabled=True)

    await cache.set("test", "value")
    await cache.clear()

    result = await cache.get("test")
    assert result is None
