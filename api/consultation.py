"""
简化的咨询API

只保留第一版核心功能
"""
from fastapi import APIRouter, HTTPException, Request
from .core.response_models import (
    ConsultationRequest,
    ConsultationResponse,
    DataResponse
)

router = APIRouter(prefix="/api/consultation", tags=["咨询服务"])


@router.post("/ask", response_model=DataResponse)
async def ask_consultation(payload: ConsultationRequest, request: Request):
    """提交咨询问题"""
    try:
        # 简化实现 - 直接导入需要的agent
        from api.chat_handler import get_session_agents
        agent = get_session_agents(request.state.session_id).consultant_agent
        async with agent:
            result = await agent.consult(payload.question)

        return DataResponse(
            message="咨询处理成功",
            data={"answer": result, "question": payload.question}
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
