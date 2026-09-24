"""
测试 Redis State Store 功能
"""

import pytest
from config.redis_config import RedisStateStore

pytestmark = pytest.mark.redis_integration


@pytest.mark.asyncio
async def test_save_and_load_state():
    """测试状态保存和加载"""
    store = RedisStateStore()

    session_id = "test_session_123"
    state_data = {
        "current_state": "ESCALATION",
        "incident_data": {
            "severity": "P1",
            "service": "payment-api",
        },
        "history": ["User reported issue", "Severity classified"],
    }

    # 保存状态
    success = await store.save_state(session_id, state_data, ttl=60)
    assert success is True

    # 加载状态
    loaded_state = await store.load_state(session_id)
    assert loaded_state is not None
    assert loaded_state["current_state"] == "ESCALATION"
    assert loaded_state["incident_data"]["severity"] == "P1"

    # 清理
    await store.delete_state(session_id)


@pytest.mark.asyncio
async def test_delete_state():
    """测试状态删除"""
    store = RedisStateStore()

    session_id = "test_session_delete"
    state_data = {"test": "data"}

    await store.save_state(session_id, state_data)

    # 删除状态
    success = await store.delete_state(session_id)
    assert success is True

    # 验证已删除
    loaded_state = await store.load_state(session_id)
    assert loaded_state is None


@pytest.mark.asyncio
async def test_suspend_stack():
    """测试 Suspend Stack 保存和加载"""
    store = RedisStateStore()

    session_id = "test_suspend_session"
    suspend_stack = [
        {
            "state": "ESCALATION",
            "data": {"severity": "P1"},
        },
        {
            "state": "RUNBOOK_LOOKUP",
            "data": {"query": "redis OOM"},
        },
    ]

    # 保存 suspend stack
    success = await store.save_suspend_stack(session_id, suspend_stack)
    assert success is True

    # 加载 suspend stack
    loaded_stack = await store.load_suspend_stack(session_id)
    assert len(loaded_stack) == 2
    assert loaded_stack[0]["state"] == "ESCALATION"
    assert loaded_stack[1]["state"] == "RUNBOOK_LOOKUP"


@pytest.mark.asyncio
async def test_extend_ttl():
    """测试 TTL 延长"""
    store = RedisStateStore()

    session_id = "test_ttl_session"
    state_data = {"test": "data"}

    await store.save_state(session_id, state_data, ttl=60)

    # 延长 TTL
    success = await store.extend_ttl(session_id, ttl=120)
    assert success is True

    # 清理
    await store.delete_state(session_id)


@pytest.mark.asyncio
async def test_nonexistent_state():
    """测试加载不存在的状态"""
    store = RedisStateStore()

    loaded_state = await store.load_state("nonexistent_session")
    assert loaded_state is None

    loaded_stack = await store.load_suspend_stack("nonexistent_session")
    assert loaded_stack == []
