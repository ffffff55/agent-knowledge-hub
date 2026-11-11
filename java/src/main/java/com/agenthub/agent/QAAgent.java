package com.agenthub.agent;

import com.agenthub.model.QAResult;
import com.agenthub.service.KnowledgeGraphService;
import com.agenthub.service.VectorStoreService;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 问答 Agent (Java版)
 *
 * 实现 GraphRAG 混合检索:
 *   1. 向量语义检索 (VectorStore)
 *   2. 知识图谱检索 (Neo4j Cypher)
 *   3. 混合重排序
 *   4. LLM 答案生成
 */
@Component
public class QAAgent {

    private static final String ANSWER_PROMPT = """
            你是一个专业的企业知识问答助手。根据检索到的上下文信息回答用户问题。
            要求：答案必须基于上下文，引用来源，如果信息不足请告知用户。
            """;

    private final ChatClient chatClient;
    private final VectorStoreService vectorStoreService;
    private final KnowledgeGraphService knowledgeGraphService;

    public QAAgent(ChatClient.Builder chatClientBuilder,
                   VectorStoreService vectorStoreService,
                   KnowledgeGraphService knowledgeGraphService) {
        this.chatClient = chatClientBuilder.build();
        this.vectorStoreService = vectorStoreService;
        this.knowledgeGraphService = knowledgeGraphService;
    }

    public QAResult answer(String question) {
        List<String> reasoning = new ArrayList<>();

        // Step 1: 向量检索
        List<QAResult.RetrievedContext> vectorResults = vectorStoreService.search(question, 5);
        reasoning.add("向量检索: " + vectorResults.size() + " 条结果");

        // Step 2: 图谱检索
        List<QAResult.RetrievedContext> graphResults = knowledgeGraphService.searchByQuestion(question);
        reasoning.add("图谱检索: " + graphResults.size() + " 条结果");

        // Step 3: 合并重排序
        List<QAResult.RetrievedContext> merged = hybridRerank(vectorResults, graphResults);
        List<QAResult.RetrievedContext> topContexts = merged.subList(0, Math.min(8, merged.size()));

        // Step 4: 生成答案
        String contextText = buildContextText(topContexts);
        String answerText = generateAnswer(question, contextText);
        reasoning.add("答案生成完成");

        return QAResult.builder()
                .question(question)
                .answer(answerText)
                .confidence(calcConfidence(topContexts))
                .intent("factoid")
                .contexts(topContexts)
                .reasoningSteps(reasoning)
                .build();
    }

    private List<QAResult.RetrievedContext> hybridRerank(
            List<QAResult.RetrievedContext> vector,
            List<QAResult.RetrievedContext> graph) {
        List<QAResult.RetrievedContext> all = new ArrayList<>();
        vector.forEach(c -> { c.setScore(c.getScore() * 1.0); all.add(c); });
        graph.forEach(c -> { c.setScore(c.getScore() * 1.2); all.add(c); });
        all.sort((a, b) -> Double.compare(b.getScore(), a.getScore()));
        return all;
    }

    private String buildContextText(List<QAResult.RetrievedContext> contexts) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < contexts.size(); i++) {
            QAResult.RetrievedContext c = contexts.get(i);
            sb.append(String.format("[来源 %d: %s | 分数: %.2f]\n%s\n\n",
                    i + 1, c.getSource(), c.getScore(), c.getContent()));
        }
        return sb.toString();
    }

    private String generateAnswer(String question, String contextText) {
        return chatClient.prompt(new Prompt(List.of(
                new SystemMessage(ANSWER_PROMPT),
                new UserMessage("上下文:\n" + contextText + "\n\n问题: " + question)
        ))).call().content();
    }

    private double calcConfidence(List<QAResult.RetrievedContext> contexts) {
        if (contexts.isEmpty()) return 0.0;
        return Math.min(contexts.stream().mapToDouble(QAResult.RetrievedContext::getScore).average().orElse(0), 1.0);
    }
}
