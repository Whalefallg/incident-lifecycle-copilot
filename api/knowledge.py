"""
知识库管理API
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from api.core.security import require_admin

router = APIRouter(prefix="/api/knowledge", tags=["知识库管理"])


class KnowledgeItem(BaseModel):
    id: int = None
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=10000)
    category: str = Field(default="general", max_length=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class DraftDecision(BaseModel):
    actor: str = Field(min_length=1, max_length=200)


@router.get("/")
async def get_all_knowledge():
    """获取所有知识条目"""
    try:
        from services.knowledge_service import KnowledgeService
        knowledge_service = KnowledgeService()
        if not knowledge_service.initialized:
            await knowledge_service.initialize()
        entries = knowledge_service.get_all_documents()

        # 安全获取categories，避免出错
        try:
            categories = knowledge_service.get_all_categories()
        except Exception as e:
            print(f"获取categories失败: {e}")
            categories = []

        return {
            "documents": entries or [],
            "categories": categories or [],
            "total_count": len(entries) if entries else 0,
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取知识库失败: {str(e)}")


@router.get("/drafts/{session_id}")
async def list_postmortem_drafts(session_id: str):
    """List persisted postmortem drafts and their approval audit fields."""
    from api.chat_handler import get_conversation_repository

    snapshot = await (await get_conversation_repository()).load(session_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"drafts": snapshot.postmortem_context.drafts}


async def _transition_draft(session_id: str, draft_id: str, action: str, actor: str):
    from api.chat_handler import get_conversation_repository
    from conversation.models import utc_now
    from conversation.repository import ConcurrentConversationUpdate
    from knowledge.approval import KnowledgeDraftStatus

    repository = await get_conversation_repository()
    for attempt in range(3):
        snapshot = await repository.load(session_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Conversation not found")
        draft = next(
            (item for item in snapshot.postmortem_context.drafts if item.draft_id == draft_id),
            None,
        )
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")

        if action == "review" and draft.status == KnowledgeDraftStatus.DRAFT:
            draft.status = KnowledgeDraftStatus.REVIEWED
            draft.reviewed_by = actor
            draft.reviewed_at = utc_now()
        elif action == "approve" and draft.status == KnowledgeDraftStatus.REVIEWED:
            draft.status = KnowledgeDraftStatus.APPROVED
            draft.approved_by = actor
            draft.approved_at = utc_now()
        elif action == "reject" and draft.status in {
            KnowledgeDraftStatus.DRAFT,
            KnowledgeDraftStatus.REVIEWED,
        }:
            draft.status = KnowledgeDraftStatus.REJECTED
            draft.reviewed_by = actor
            draft.reviewed_at = utc_now()
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid {action} transition from {draft.status.value}",
            )
        try:
            await repository.save(snapshot, snapshot.revision)
            return draft
        except ConcurrentConversationUpdate:
            if attempt == 2:
                raise HTTPException(status_code=409, detail="Concurrent draft update")


@router.post("/drafts/{session_id}/{draft_id}/review", dependencies=[Depends(require_admin)])
async def review_postmortem_draft(session_id: str, draft_id: str, decision: DraftDecision):
    return await _transition_draft(session_id, draft_id, "review", decision.actor)


@router.post("/drafts/{session_id}/{draft_id}/approve", dependencies=[Depends(require_admin)])
async def approve_postmortem_draft(session_id: str, draft_id: str, decision: DraftDecision):
    return await _transition_draft(session_id, draft_id, "approve", decision.actor)


@router.post("/drafts/{session_id}/{draft_id}/reject", dependencies=[Depends(require_admin)])
async def reject_postmortem_draft(session_id: str, draft_id: str, decision: DraftDecision):
    return await _transition_draft(session_id, draft_id, "reject", decision.actor)


@router.get("/{knowledge_id}")
async def get_knowledge(knowledge_id: int):
    """获取特定知识条目"""
    try:
        from services.knowledge_service import KnowledgeService
        knowledge_service = KnowledgeService()
        if not knowledge_service.initialized:
            await knowledge_service.initialize()
        entry = knowledge_service.get_document(knowledge_id)
        if not entry:
            raise HTTPException(status_code=404, detail="知识条目不存在")
        return {
            "status": "success",
            "data": entry
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取知识条目失败: {str(e)}")


@router.post("/", dependencies=[Depends(require_admin)])
async def add_knowledge(item: KnowledgeItem):
    """添加新的知识条目"""
    try:
        from services.knowledge_service import KnowledgeService
        knowledge_service = KnowledgeService()
        if not knowledge_service.initialized:
            await knowledge_service.initialize()
        # 将问答组合成文档内容
        content = f"问题: {item.question}\n答案: {item.answer}"
        result = await knowledge_service.add_document(
            content=content,
            category=item.category
        )
        return {
            "status": "success",
            "message": "知识条目添加成功",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加知识条目失败: {str(e)}")


@router.put("/{knowledge_id}", dependencies=[Depends(require_admin)])
async def update_knowledge(knowledge_id: int, item: KnowledgeItem):
    """更新知识条目"""
    try:
        from services.knowledge_service import KnowledgeService
        knowledge_service = KnowledgeService()
        if not knowledge_service.initialized:
            await knowledge_service.initialize()
        # 将问答组合成文档内容
        content = f"问题: {item.question}\n答案: {item.answer}"
        result = await knowledge_service.update_document(
            doc_id=knowledge_id,
            content=content,
            category=item.category
        )
        if not result:
            raise HTTPException(status_code=404, detail="知识条目不存在")
        return {
            "status": "success",
            "message": "知识条目更新成功",
            "data": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新知识条目失败: {str(e)}")


@router.delete("/{knowledge_id}", dependencies=[Depends(require_admin)])
async def delete_knowledge(knowledge_id: int):
    """删除知识条目"""
    try:
        from services.knowledge_service import KnowledgeService
        knowledge_service = KnowledgeService()
        if not knowledge_service.initialized:
            await knowledge_service.initialize()
        result = await knowledge_service.delete_document(knowledge_id)
        if not result:
            raise HTTPException(status_code=404, detail="知识条目不存在")
        return {
            "status": "success",
            "message": "知识条目删除成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除知识条目失败: {str(e)}")


@router.post("/search")
async def search_knowledge(request: SearchRequest):
    """搜索知识库"""
    try:
        from services.knowledge_service import KnowledgeService
        knowledge_service = KnowledgeService()
        if not knowledge_service.initialized:
            await knowledge_service.initialize()
        results = await knowledge_service.search(request.query)
        return {
            "status": "success",
            "data": results,
            "count": len(results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索知识库失败: {str(e)}")
