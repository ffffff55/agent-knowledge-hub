"""
FastAPI 入口 — 企业知识管理系统 REST API

提供三组接口:
  1. /api/ingest   — 文档上传 & 入库
  2. /api/qa       — 智能问答
  3. /api/admin    — 管理（统计、更新触发）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger("api.main")

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.doc_parser_agent import DocParserAgent
from agents.knowledge_extract_agent import KnowledgeExtractAgent
from agents.knowledge_update_agent import ChangeType, DocumentChange, KnowledgeUpdateAgent
from agents.qa_agent import QAAgent
from config import settings
from orchestrator.graph import build_knowledge_graph_workflow
from services.knowledge_graph import KnowledgeGraphService
from services.vector_store import VectorStoreService

vector_store = VectorStoreService()
knowledge_graph = KnowledgeGraphService()
workflows: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)

    # 核心依赖初始化失败必须直接报错，避免服务"带病运行"导致后续 NoneType 崩溃
    logger.info("Initializing vector store (backend=%s, host=%s:%s)...", settings.vector_store_type, settings.chroma_host, settings.chroma_port)
    await vector_store.init()
    logger.info("Vector store initialized.")

    logger.info("Initializing knowledge graph (uri=%s)...", settings.neo4j_uri)
    await knowledge_graph.init()
    logger.info("Knowledge graph initialized.")

    logger.info("Building workflows...")
    workflows.update(
        build_knowledge_graph_workflow(vector_store=vector_store, knowledge_graph=knowledge_graph)
    )
    logger.info("AgentKnowledgeHub API startup complete.")
    yield
    await knowledge_graph.close()


app = FastAPI(
    title="AgentKnowledgeHub — 多Agent企业知识管理系统",
    description="支持多模态RAG、知识图谱、增量更新的企业级知识管理 API",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request / Response Models ────────────────────────────────

class QuestionRequest(BaseModel):
    question: str


class QuestionResponse(BaseModel):
    question: str
    answer: str
    confidence: float
    intent: str
    sources: list[dict[str, Any]]
    reasoning_steps: list[str]


class IngestResponse(BaseModel):
    file_name: str
    chunks_count: int
    entities_count: int
    relations_count: int
    status: str
    parse_mode: str = "unknown"  # text | ocr | vision | ocr+vision | failed
    pages: int = 0


class StatsResponse(BaseModel):
    vector_store: dict[str, Any]
    knowledge_graph: dict[str, Any]


class UpdateRequest(BaseModel):
    file_path: str
    change_type: str = "modified"


class UpdateResponse(BaseModel):
    file_path: str
    vectors_added: int
    vectors_deleted: int
    entities_added: int
    relations_added: int
    success: bool
    processing_time_ms: float


# ── Ingest Endpoints ─────────────────────────────────────────
# 入库改为「后台任务 + 可取消」：上传请求立即返回 task_id，前端轮询状态，
# 随时可调用 /api/ingest/cancel/{task_id} 中止解析（避免扫描件等大文件卡死）。

ingest_tasks: dict[str, dict] = {}


async def _run_ingest_for_file(save_path: str, file_name: str, task_id: str) -> None:
    """后台执行单文件入库；支持 asyncio 取消（停止解析）。"""
    try:
        ingest_wf = workflows.get("ingest")
        if not ingest_wf:
            raise RuntimeError("Ingest workflow not initialized")
        result = await ingest_wf.ainvoke({"file_paths": [save_path]})
        chunks = result.get("chunks", [])
        extractions = result.get("extractions", [])
        total_entities = sum(len(e.entities) for e in extractions)
        total_relations = sum(len(e.relations) for e in extractions)
        # 解析模式诊断：用于向前端解释「为何 embedding 消耗少」
        parse_mode = chunks[0].metadata.get("parse_mode", "unknown") if chunks else "unknown"
        pages = int(chunks[0].metadata.get("pages", 0) or 0) if chunks else 0
        ingest_tasks[task_id]["result"] = IngestResponse(
            file_name=file_name,
            chunks_count=len(chunks),
            entities_count=total_entities,
            relations_count=total_relations,
            status="success",
            parse_mode=parse_mode,
            pages=pages,
        )
        ingest_tasks[task_id]["status"] = "done"
    except asyncio.CancelledError:
        ingest_tasks[task_id]["status"] = "cancelled"
        logger.info("Ingest task %s cancelled", task_id)
        raise
    except Exception as exc:  # noqa: BLE001
        ingest_tasks[task_id]["status"] = "error"
        ingest_tasks[task_id]["error"] = str(exc)
        logger.exception("Ingest task %s failed", task_id)


def _start_ingest(file: UploadFile) -> dict:
    """保存文件并启动后台入库任务，返回 {file_name, task_id}。"""
    file_name = file.filename or "unknown"
    save_path = os.path.join(settings.upload_dir, file_name)
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    task_id = uuid.uuid4().hex
    ingest_tasks[task_id] = {
        "status": "running",
        "result": None,
        "error": None,
        "file_name": file_name,
        "task": None,
    }
    task = asyncio.create_task(_run_ingest_for_file(save_path, file_name, task_id))
    ingest_tasks[task_id]["task"] = task
    return {"file_name": file_name, "task_id": task_id}


@app.post("/api/ingest/upload", tags=["文档入库"])
async def upload_document(file: UploadFile = File(...)):
    """上传并异步解析文档，返回 task_id 供前端轮询/取消。"""
    return _start_ingest(file)


@app.post("/api/ingest/batch", tags=["文档入库"])
async def upload_batch(files: list[UploadFile] = File(...)):
    """批量上传文档，逐个启动后台入库任务。"""
    return [_start_ingest(f) for f in files]


@app.get("/api/ingest/status/{task_id}", tags=["文档入库"])
async def ingest_status(task_id: str):
    """查询入库任务状态：running / done / cancelled / error。"""
    t = ingest_tasks.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "task_id": task_id,
        "status": t["status"],
        "file_name": t["file_name"],
        "result": t["result"].model_dump() if t["result"] else None,
        "error": t["error"],
    }


@app.post("/api/ingest/cancel/{task_id}", tags=["文档入库"])
async def ingest_cancel(task_id: str):
    """中止正在进行的入库任务（停止解析）。"""
    t = ingest_tasks.get(task_id)
    if not t:
        return {"ok": False, "reason": "not_found"}
    if t["status"] in ("done", "cancelled", "error"):
        return {"ok": True, "status": t["status"]}
    if t["task"] is not None:
        t["task"].cancel()
    return {"ok": True, "status": "cancelling"}


# ── QA Endpoints ─────────────────────────────────────────────

@app.post("/api/qa/ask", response_model=QuestionResponse, tags=["智能问答"])
async def ask_question(req: QuestionRequest):
    """智能问答 — 混合检索 + 知识图谱推理"""
    qa_wf = workflows.get("qa")
    if not qa_wf:
        raise HTTPException(status_code=503, detail="QA workflow not initialized")

    result = await qa_wf.ainvoke({"question": req.question})
    qa_result = result.get("result")
    if not qa_result:
        raise HTTPException(status_code=500, detail="QA failed")

    return QuestionResponse(
        question=qa_result.question,
        answer=qa_result.answer,
        confidence=qa_result.confidence,
        intent=qa_result.intent.value,
        sources=[
            {"content": c.content[:200], "source": c.source, "score": c.score, "type": c.retrieval_type}
            for c in qa_result.contexts
        ],
        reasoning_steps=qa_result.reasoning_steps,
    )


@app.post("/api/qa/ask/stream", tags=["智能问答"])
async def ask_question_stream(req: QuestionRequest):
    """
    流式问答 — 服务端以 SSE (text/event-stream) 逐 token 推送答案。

    事件格式（每行 ``data: <json>``，事件间以空行分隔）：
      - {"type": "token",  "content": "..."}   增量文本片段
      - {"type": "done",   "answer": ..., "confidence": ..., "sources": [...], "reasoning_steps": [...], "intent": ...}
      - {"type": "error",  "message": "..."}
    末尾以 ``data: [DONE]`` 结束。
    """
    qa_agent = workflows.get("qa_agent")
    if not qa_agent:
        raise HTTPException(status_code=503, detail="QA agent not initialized")

    async def event_generator():
        async for event in qa_agent.stream_answer(req.question):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭反向代理缓冲，确保逐 token 下发
        },
    )



# ── Admin Endpoints ──────────────────────────────────────────

@app.get("/api/admin/stats", response_model=StatsResponse, tags=["系统管理"])
async def get_stats():
    """获取系统统计信息"""
    vs_stats = await vector_store.get_stats()
    kg_stats = await knowledge_graph.get_stats()
    return StatsResponse(vector_store=vs_stats, knowledge_graph=kg_stats)


@app.post("/api/admin/update", response_model=UpdateResponse, tags=["系统管理"])
async def trigger_update(req: UpdateRequest):
    """手动触发知识更新"""
    update_wf = workflows.get("update")
    if not update_wf:
        raise HTTPException(status_code=503, detail="Update workflow not initialized")

    change = DocumentChange(
        file_path=req.file_path,
        change_type=ChangeType(req.change_type),
    )
    result = await update_wf.ainvoke({"changes": [change]})
    results = result.get("results", [])
    if not results:
        raise HTTPException(status_code=500, detail="Update failed")

    r = results[0]
    return UpdateResponse(
        file_path=r.change.file_path,
        vectors_added=r.vectors_added,
        vectors_deleted=r.vectors_deleted,
        entities_added=r.entities_added,
        relations_added=r.relations_added,
        success=r.success,
        processing_time_ms=r.processing_time_ms,
    )


@app.get("/api/health", tags=["系统管理"])
async def health():
    return {"status": "ok", "service": "AgentKnowledgeHub"}


# ── 网页界面（静态资源）───────────────────────────────────────
# 在所有 API 路由注册完毕后再挂载到根路径，确保 /api/* 与 /docs 优先匹配；
# 其余路径（如 "/"）回退到 web/index.html，作为单页应用入口。
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host=settings.api_host, port=settings.api_port, reload=True)
