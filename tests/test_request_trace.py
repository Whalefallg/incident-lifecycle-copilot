"""请求追踪工具单元测试"""

import logging

from config.request_trace import get_trace_id, new_trace_id, set_trace_id, trace_step


def test_new_trace_id_is_unique():
    ids = {new_trace_id() for _ in range(10)}
    assert len(ids) == 10


def test_set_trace_id_persists_in_context():
    set_trace_id("abc12345")
    assert get_trace_id() == "abc12345"


def test_trace_step_logs_timing(caplog):
    set_trace_id("test0001")
    with caplog.at_level(logging.INFO):
        with trace_step("unit_test_step", agent="TestAgent"):
            pass
    assert any("trace_id=test0001" in r.message for r in caplog.records)
    assert any("unit_test_step" in r.message for r in caplog.records)
