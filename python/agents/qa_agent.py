"""
问答 Agent — 混合检索 (Vector + Graph) + 多跳推理 + 答案生成

核心能力:
  1. 意图识别 & 查询改写
  2. 向量检索 (语义相似度)
  3. 图谱检索 (Cypher 查询 / 子图遍历)
  4. 混合排序 & 重排序
  5. 基于检索结果的答案生成（带引用来源）
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings

logger = logging.getLogger(__name__)


class QueryIntent(str, Enum):
    FACTOID = "factoid"           # 事实型问题
    ANALYTICAL = "analytical"     # 分析型问题
    COMPARATIVE = "comparative"   # 对比型问题
    PROCEDURAL = "procedural"     # 流程型问题
    EXPLORATORY = "exploratory"   # 探索型问题


@dataclass
class RetrievedContext:
    content: str
    source: str
    score: float
    retrieval_type: str  # "vector" | "graph" | "hybrid"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QAResult:
    question: str
    answer: str
    contexts: list[RetrievedContext]
    intent: QueryIntent
    confidence: float
    reasoning_steps: list[str] = field(default_factory=list)


ANALYZE_PROMPT = """\
你是一个查询分析器。根据用户的**问题**，一次性完成以下分析，并**只**以 JSON 返回，不要输出多余文字：
1. 意图类别（取其一）: factoid / analytical / comparative / procedural / exploratory
2. 1-3 个适合向量检索的查询（可改写/扩展原问题，使语义更完整）
3. 抽取的实体列表（用于知识图谱检索；若问题中无明显实体则为空数组）
4. 关键词列表

返回格式（严格 JSON）:
{"intent":"factoid","queries":["查询1"],"entities":["实体1"],"keywords":["关键词1"]}
"""

CYPHER_GENERATION_PROMPT = """\
你是一个 Neo4j Cypher 查询生成专家。根据用户问题和提取的实体，生成 Cypher 查询。

知识图谱 Schema:
- 节点标签: Person, Organization, Technology, Product, Concept, Location
- 关系类型: belongs_to, works_at, located_in, developed_by, related_to, part_of, uses, depends_on
- 节点属性: name, type, description, created_at, version

生成 1-2 条 Cypher 查询，返回 JSON: {"queries": ["MATCH ...", "MATCH ..."]}
只返回 JSON，不要其他文字。
"""

ANSWER_PROMPT = """\
你是一个专业的企业知识问答助手。根据检索到的上下文信息回答用户问题。

要求：
1. 答案必须基于提供的上下文，不要编造
2. 如果上下文信息不足，明确告知用户
3. 引用信息来源（如 [来源: xxx]）
4. 如果涉及多个信息源，综合分析后给出结论
5. 保持专业、准确、简洁
"""


class QAAgent:
    """
    问答 Agent

    工作流:
      query → intent_classify → rewrite → parallel_retrieve → rerank → generate_answer
    """

    def __init__(
        self,
        vector_store: Any = None,
        knowledge_graph: Any = None,
    ) -> None:
        self.llm = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0,
            streaming=True,
        )
        self.vector_store = vector_store
        self.knowledge_graph = knowledge_graph

    # ── public API ───────────────────────────────────────────

    async def answer(self, question: str) -> QAResult:
        """完整问答流程"""
        analysis = await self._analyze_query(question)
        intent = analysis["intent"]

        vector_contexts = await self._vector_retrieve(analysis)
        graph_contexts = await self._graph_retrieve(question, analysis)

        all_contexts = self._hybrid_rerank(vector_contexts + graph_contexts)
        top_contexts = all_contexts[:8]

        answer_text, reasoning = await self._generate_answer(question, top_contexts, intent)

        return QAResult(
            question=question,
            answer=answer_text,
            contexts=top_contexts,
            intent=intent,
            confidence=self._calc_confidence(top_contexts),
            reasoning_steps=reasoning,
        )

    # ── streaming answer ──────────────────────────────────────

    async def stream_answer(self, question: str) -> AsyncIterator[dict]:
        """
        流式问答生成器。

        先执行完整的「意图识别 → 检索 → 重排」流程（与非流式一致），
        再逐 token 通过 ``self.llm.astream`` 产出答案。

        产出事件 dict：
          - {"type": "token",   "content": "<增量文本>"}      每个增量片段
          - {"type": "done",    "answer": ..., "confidence": ...,
                                "sources": [...], "reasoning_steps": [...], "intent": ...}
          - {"type": "error",   "message": "<错误信息>"}
        """
        try:
            # ── 前置链（已尽量精简 LLM 调用次数）──
            # 1) 一次 LLM 调用完成 意图识别 + 改写 + 实体抽取
            # 2) 向量检索 与 图谱检索 并行（图谱带超时兜底，无实体则跳过）
            # 立即向客户端反馈状态，避免长链路下用户以为"没响应"
            yield {"type": "status", "message": "正在分析查询并检索知识库（首次检索约需 10+ 秒）…"}
            analysis = await self._analyze_query(question)
            intent = analysis["intent"]

            vector_contexts, graph_contexts = await asyncio.gather(
                self._vector_retrieve(analysis),
                self._safe_graph_retrieve(question, analysis),
            )

            all_contexts = self._hybrid_rerank(vector_contexts + graph_contexts)
            top_contexts = all_contexts[:8]

            context_text = "\n\n".join(
                f"[来源 {i+1}: {c.source} | 类型: {c.retrieval_type} | 分数: {c.score:.2f}]\n{c.content}"
                for i, c in enumerate(top_contexts)
            )
            reasoning_steps = [
                f"识别问题意图: {intent.value}",
                f"检索到 {len(top_contexts)} 条相关上下文",
                f"向量检索: {sum(1 for c in top_contexts if c.retrieval_type == 'vector')} 条",
                f"图谱检索: {sum(1 for c in top_contexts if c.retrieval_type == 'graph')} 条",
            ]

            messages = [
                SystemMessage(content=ANSWER_PROMPT),
                HumanMessage(content=f"上下文信息:\n{context_text}\n\n用户问题: {question}"),
            ]

            collected: list[str] = []
            async for chunk in self.llm.astream(messages):
                delta = chunk.content
                if isinstance(delta, list):
                    delta = "".join(str(part) for part in delta)
                elif not isinstance(delta, str):
                    delta = str(delta)
                if delta:
                    collected.append(delta)
                    yield {"type": "token", "content": delta}

            answer_text = "".join(collected)
            reasoning_steps.append("答案生成完成")

            sources = [
                {
                    "content": c.content[:200],
                    "source": c.source,
                    "score": c.score,
                    "type": c.retrieval_type,
                }
                for c in top_contexts
            ]

            yield {
                "type": "done",
                "answer": answer_text,
                "confidence": self._calc_confidence(top_contexts),
                "sources": sources,
                "reasoning_steps": reasoning_steps,
                "intent": intent.value,
            }
        except Exception as exc:  # noqa: BLE001 — 统一以 SSE error 事件上报
            yield {"type": "error", "message": str(exc)}

    # ── 合并：意图识别 + 查询改写（单次 LLM 调用，降低首 token 延迟）──

    async def _analyze_query(self, question: str) -> dict:
        """一次 LLM 调用同时完成 意图识别 + 查询改写 + 实体抽取。

        返回 dict: {"intent": QueryIntent, "queries": [...], "entities": [...], "keywords": [...]}
        解析失败时回退为直接用原问题检索。
        """
        messages = [
            SystemMessage(content=ANALYZE_PROMPT),
            HumanMessage(content=question),
        ]
        resp = await self.llm.ainvoke(messages)
        raw = resp.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            return {"intent": QueryIntent.FACTOID, "queries": [question], "entities": [], "keywords": []}

        intent_str = str(data.get("intent", "factoid")).lower()
        intent = next((i for i in QueryIntent if i.value == intent_str), QueryIntent.FACTOID)
        return {
            "intent": intent,
            "queries": data.get("queries") or [question],
            "entities": data.get("entities") or [],
            "keywords": data.get("keywords") or [],
        }

    # ── vector retrieval ─────────────────────────────────────

    async def _vector_retrieve(self, analysis: dict) -> list[RetrievedContext]:
        if not self.vector_store:
            return []

        contexts: list[RetrievedContext] = []
        for query in analysis.get("queries", []):
            results = await self.vector_store.search(query, top_k=5)
            for doc, score in results:
                contexts.append(RetrievedContext(
                    content=doc.get("content", ""),
                    source=doc.get("source", "vector_store"),
                    score=score,
                    retrieval_type="vector",
                    metadata=doc.get("metadata", {}),
                ))
        return contexts

    # ── graph retrieval ──────────────────────────────────────

    async def _graph_retrieve(self, question: str, analysis: dict) -> list[RetrievedContext]:
        if not self.knowledge_graph:
            return []

        # 无实体直接跳过：避免无谓的 LLM Cypher 生成（单次调用 ~6s），显著降低首 token 延迟
        entities = analysis.get("entities", [])
        if not entities:
            return []

        import json
        messages = [
            SystemMessage(content=CYPHER_GENERATION_PROMPT),
            HumanMessage(content=f"问题: {question}\n实体: {entities}"),
        ]
        resp = await self.llm.ainvoke(messages)
        try:
            cleaned = resp.content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            cypher_data = json.loads(cleaned)
        except (json.JSONDecodeError, IndexError):
            cypher_data = {"queries": []}

        contexts: list[RetrievedContext] = []
        for cypher in cypher_data.get("queries", []):
            try:
                records = await self.knowledge_graph.execute_cypher(cypher)
                for record in records:
                    contexts.append(RetrievedContext(
                        content=str(record),
                        source="knowledge_graph",
                        score=0.8,
                        retrieval_type="graph",
                        metadata={"cypher": cypher},
                    ))
            except Exception:
                continue
        return contexts

    async def _safe_graph_retrieve(
        self, question: str, analysis: dict
    ) -> list[RetrievedContext]:
        """
        带超时兜底的图谱检索。

        图谱检索需要先 LLM 生成 Cypher 再查 Neo4j，往往是整条链路最慢的一环，
        且对问候/简单问题意义不大。这里给它 8s 超时，超时或失败直接返回空，
        绝不阻塞主问答链路，从而显著压低首 token 延迟。
        """
        try:
            return await asyncio.wait_for(
                self._graph_retrieve(question, analysis),
                timeout=8.0,
            )
        except asyncio.TimeoutError:
            logger.warning("图谱检索超时（>8s），已跳过，不影响答案生成")
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("图谱检索失败，已跳过：%s", exc)
            return []

    # ── hybrid reranking ─────────────────────────────────────

    @staticmethod
    def _hybrid_rerank(contexts: list[RetrievedContext]) -> list[RetrievedContext]:
        """
        混合重排序：向量分数 + 图谱分数加权
        图谱检索结果天然带有结构化关系，给予略高权重
        """
        weight_map = {"vector": 1.0, "graph": 1.2, "hybrid": 1.1}
        for ctx in contexts:
            ctx.score *= weight_map.get(ctx.retrieval_type, 1.0)

        seen: set[str] = set()
        unique: list[RetrievedContext] = []
        for ctx in contexts:
            key = ctx.content[:100]
            if key not in seen:
                seen.add(key)
                unique.append(ctx)

        unique.sort(key=lambda c: c.score, reverse=True)
        return unique

    # ── answer generation ────────────────────────────────────

    async def _generate_answer(
        self,
        question: str,
        contexts: list[RetrievedContext],
        intent: QueryIntent,
    ) -> tuple[str, list[str]]:
        context_text = "\n\n".join(
            f"[来源 {i+1}: {c.source} | 类型: {c.retrieval_type} | 分数: {c.score:.2f}]\n{c.content}"
            for i, c in enumerate(contexts)
        )
        reasoning_steps = [
            f"识别问题意图: {intent.value}",
            f"检索到 {len(contexts)} 条相关上下文",
            f"向量检索: {sum(1 for c in contexts if c.retrieval_type == 'vector')} 条",
            f"图谱检索: {sum(1 for c in contexts if c.retrieval_type == 'graph')} 条",
        ]

        messages = [
            SystemMessage(content=ANSWER_PROMPT),
            HumanMessage(content=f"上下文信息:\n{context_text}\n\n用户问题: {question}"),
        ]
        resp = await self.llm.ainvoke(messages)
        reasoning_steps.append("答案生成完成")
        return resp.content, reasoning_steps

    @staticmethod
    def _calc_confidence(contexts: list[RetrievedContext]) -> float:
        if not contexts:
            return 0.0
        avg_score = sum(c.score for c in contexts) / len(contexts)
        return min(avg_score, 1.0)
