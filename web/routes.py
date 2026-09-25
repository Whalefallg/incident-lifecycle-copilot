"""
Web界面路由

处理前端页面渲染和聊天功能
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from api.chat_handler import ProcessUserInput_stream, reset_session
import logging

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="web/templates")

router = APIRouter(tags=["Web界面"])

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    state: str | None = None

@router.get("/", response_class=HTMLResponse, summary="主页")
async def read_root(request: Request):
    """Incident Lifecycle Copilot 主界面"""
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/chat/stream", summary="流式聊天")
async def chat_stream_endpoint(chat: ChatRequest, request: Request):
    """处理流式聊天请求"""
    async def token_generator():
        async for token in ProcessUserInput_stream(
            chat.message, session_id=request.state.session_id
        ):
            yield token
    return StreamingResponse(token_generator(), media_type="text/plain")

@router.post("/chat", summary="兼容性聊天接口")
async def chat_endpoint(chat: ChatRequest, request: Request):
    """兼容性聊天接口，建议使用/chat/stream"""
    async def token_generator():
        async for token in ProcessUserInput_stream(
            chat.message, session_id=request.state.session_id
        ):
            yield token
    return StreamingResponse(token_generator(), media_type="text/plain")


@router.delete("/chat/session", summary="重置当前事故会话")
async def reset_chat_session(request: Request):
    await reset_session(request.state.session_id)
    return {"status": "ok", "message": "Incident session reset"}

@router.get("/knowledge", response_class=HTMLResponse, summary="知识库管理页面")
async def knowledge_page(request: Request):
    """Runbook & postmortem knowledge base management page"""
    try:
        from api.knowledge import get_all_knowledge
        knowledge_data = await get_all_knowledge()
        documents = knowledge_data.get("documents", [])
        categories = knowledge_data.get("categories", [])
        return templates.TemplateResponse("knowledge_management.html", {
            "request": request,
            "documents": documents,
            "categories": categories
        })
    except Exception as e:
        return templates.TemplateResponse("knowledge_management.html", {
            "request": request,
            "documents": [],
            "categories": [],
            "error": str(e)
        })
