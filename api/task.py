"""
简化的任务分类API

只保留第一版核心功能
"""
from fastapi import APIRouter, HTTPException, Request
from .core.response_models import (
    TaskClassificationRequest,
    TaskClassificationResponse,
    DataResponse
)

router = APIRouter(prefix="/api/task", tags=["任务分类"])


@router.post("/classify", response_model=DataResponse)
async def classify_task(payload: TaskClassificationRequest, request: Request):
    """分类任务"""
    try:
        # 简化实现 - 直接导入需要的agent
        from api.chat_handler import get_session_agents
        agent = get_session_agents(request.state.session_id).task_agent
        result = await agent.classify_task(payload.text)

        return DataResponse(
            message="任务分类成功",
            data=result
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
