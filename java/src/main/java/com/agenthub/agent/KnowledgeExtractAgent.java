package com.agenthub.agent;

import com.agenthub.model.DocumentChunk;
import com.agenthub.model.ExtractionResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 知识抽取 Agent (Java版)
 *
 * 使用 Spring AI ChatClient 调用 LLM 从文本中抽取
 * 实体、关系、事件，生成知识图谱三元组。
 */
@Component
public class KnowledgeExtractAgent {

    private static final String SYSTEM_PROMPT = """
            你是一个专业的知识抽取引擎。给定一段文本，请提取实体和关系。
            返回 JSON 格式:
            {
              "entities": [{"name": "实体名", "type": "类型", "description": "描述"}],
              "relations": [{"head": "头实体", "relation": "关系", "tail": "尾实体", "confidence": 0.95}]
            }
            实体类型: Person, Organization, Technology, Product, Concept, Location
            关系类型: belongs_to, works_at, developed_by, related_to, part_of, uses, depends_on
            只返回 JSON。
            """;

    private final ChatClient chatClient;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public KnowledgeExtractAgent(ChatClient.Builder chatClientBuilder) {
        this.chatClient = chatClientBuilder.build();
    }

    public List<ExtractionResult> extract(List<DocumentChunk> chunks) {
        List<ExtractionResult> results = new ArrayList<>();
        Set<String> seenEntities = new HashSet<>();
        Set<String> seenRelations = new HashSet<>();

        for (DocumentChunk chunk : chunks) {
            ExtractionResult result = extractFromChunk(chunk);
            deduplicate(result, seenEntities, seenRelations);
            results.add(result);
        }
        return results;
    }

    private ExtractionResult extractFromChunk(DocumentChunk chunk) {
        try {
            String response = chatClient.prompt(new Prompt(List.of(
                    new SystemMessage(SYSTEM_PROMPT),
                    new UserMessage("请从以下文本中抽取知识：\n\n" + chunk.getContent())
            ))).call().content();

            return parseResponse(response, chunk.getChunkId());
        } catch (Exception e) {
            return ExtractionResult.builder()
                    .entities(List.of())
                    .relations(List.of())
                    .sourceChunkId(chunk.getChunkId())
                    .build();
        }
    }

    private ExtractionResult parseResponse(String raw, String sourceId) {
        try {
            String cleaned = raw.trim();
            if (cleaned.startsWith("```")) {
                cleaned = cleaned.substring(cleaned.indexOf('\n') + 1);
                cleaned = cleaned.substring(0, cleaned.lastIndexOf("```"));
            }

            JsonNode root = objectMapper.readTree(cleaned);

            List<ExtractionResult.Entity> entities = new ArrayList<>();
            if (root.has("entities")) {
                for (JsonNode e : root.get("entities")) {
                    entities.add(ExtractionResult.Entity.builder()
                            .name(e.path("name").asText())
                            .type(e.path("type").asText("Concept"))
                            .description(e.path("description").asText(""))
                            .build());
                }
            }

            List<ExtractionResult.Relation> relations = new ArrayList<>();
            if (root.has("relations")) {
                for (JsonNode r : root.get("relations")) {
                    relations.add(ExtractionResult.Relation.builder()
                            .head(r.path("head").asText())
                            .relation(r.path("relation").asText("related_to"))
                            .tail(r.path("tail").asText())
                            .confidence(r.path("confidence").asDouble(0.5))
                            .build());
                }
            }

            return ExtractionResult.builder()
                    .entities(entities)
                    .relations(relations)
                    .sourceChunkId(sourceId)
                    .build();
        } catch (Exception e) {
            return ExtractionResult.builder()
                    .entities(List.of())
                    .relations(List.of())
                    .sourceChunkId(sourceId)
                    .build();
        }
    }

    private void deduplicate(ExtractionResult result, Set<String> seenEntities, Set<String> seenRelations) {
        result.setEntities(result.getEntities().stream()
                .filter(e -> seenEntities.add(e.getName() + "::" + e.getType()))
                .toList());
        result.setRelations(result.getRelations().stream()
                .filter(r -> seenRelations.add(r.getHead() + "::" + r.getRelation() + "::" + r.getTail()))
                .toList());
    }
}
