package com.agenthub.agent;

import com.agenthub.model.DocumentChunk;
import com.agenthub.model.ExtractionResult;
import com.agenthub.service.KnowledgeGraphService;
import com.agenthub.service.VectorStoreService;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 知识更新 Agent (Java版)
 *
 * 通过 Spring Kafka 监听 CDC 事件，实现增量更新。
 * 当文档发生变更时:
 *   1. 删除旧的向量和图谱数据
 *   2. 重新解析变更文档
 *   3. 增量写入向量库和图谱
 */
@Component
public class KnowledgeUpdateAgent {

    private final DocParserAgent docParser;
    private final KnowledgeExtractAgent extractor;
    private final VectorStoreService vectorStore;
    private final KnowledgeGraphService knowledgeGraph;

    public KnowledgeUpdateAgent(DocParserAgent docParser,
                                 KnowledgeExtractAgent extractor,
                                 VectorStoreService vectorStore,
                                 KnowledgeGraphService knowledgeGraph) {
        this.docParser = docParser;
        this.extractor = extractor;
        this.vectorStore = vectorStore;
        this.knowledgeGraph = knowledgeGraph;
    }

    @KafkaListener(topics = "${app.kafka.topic:doc-changes}", groupId = "agenthub-java")
    public void handleCDCEvent(String message) {
        try {
            com.fasterxml.jackson.databind.JsonNode payload =
                    new com.fasterxml.jackson.databind.ObjectMapper().readTree(message);

            String filePath = payload.path("file_path").asText();
            String changeType = payload.path("change_type").asText("modified");

            switch (changeType) {
                case "created" -> handleCreate(filePath);
                case "modified" -> handleModify(filePath);
                case "deleted" -> handleDelete(filePath);
            }
        } catch (Exception e) {
            System.err.println("CDC event processing failed: " + e.getMessage());
        }
    }

    public void handleCreate(String filePath) throws Exception {
        List<DocumentChunk> chunks = docParser.parse(filePath);
        vectorStore.addChunks(chunks);

        List<ExtractionResult> extractions = extractor.extract(chunks);
        for (ExtractionResult ext : extractions) {
            for (ExtractionResult.Entity entity : ext.getEntities()) {
                knowledgeGraph.upsertEntity(entity);
            }
            for (ExtractionResult.Relation relation : ext.getRelations()) {
                knowledgeGraph.addRelation(relation);
            }
        }
    }

    public void handleModify(String filePath) throws Exception {
        String docId = computeDocId(filePath);
        vectorStore.deleteByDocId(docId);
        handleCreate(filePath);
    }

    public void handleDelete(String filePath) {
        String docId = computeDocId(filePath);
        vectorStore.deleteByDocId(docId);
        knowledgeGraph.deleteBySource(filePath);
    }

    private static String computeDocId(String path) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(path.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(hash).substring(0, 16);
        } catch (Exception e) {
            return String.valueOf(path.hashCode());
        }
    }
}
