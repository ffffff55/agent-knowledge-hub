package com.agenthub.service;

import com.agenthub.model.ExtractionResult;
import com.agenthub.model.QAResult;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.neo4j.driver.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 知识图谱服务 (Java版)
 *
 * 使用 Neo4j Java Driver 管理知识图谱:
 *   - 实体 CRUD (带版本号)
 *   - 关系管理
 *   - 多跳子图检索
 *   - Cypher 查询
 */
@Service
public class KnowledgeGraphService {

    @Value("${app.neo4j.uri}")
    private String uri;
    @Value("${app.neo4j.user}")
    private String user;
    @Value("${app.neo4j.password}")
    private String password;

    private Driver driver;

    @PostConstruct
    public void init() {
        try {
            driver = GraphDatabase.driver(uri, AuthTokens.basic(user, password));
            ensureIndexes();
        } catch (Exception e) {
            System.err.println("Neo4j connection failed: " + e.getMessage());
        }
    }

    @PreDestroy
    public void close() {
        if (driver != null) driver.close();
    }

    private void ensureIndexes() {
        if (driver == null) return;
        try (Session session = driver.session()) {
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.name)");
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.type)");
        }
    }

    public void upsertEntity(ExtractionResult.Entity entity) {
        if (driver == null) return;
        String cypher = """
                MERGE (e:Entity {name: $name})
                ON CREATE SET e.type = $type, e.description = $desc, e.created_at = timestamp()
                ON MATCH SET e.description = CASE WHEN $desc <> '' THEN $desc ELSE e.description END,
                             e.updated_at = timestamp()
                """;
        try (Session session = driver.session()) {
            session.run(cypher, Map.of("name", entity.getName(), "type", entity.getType(),
                    "desc", entity.getDescription()));
        }
    }

    public void addRelation(ExtractionResult.Relation relation) {
        if (driver == null) return;
        String relType = relation.getRelation().toUpperCase().replace(" ", "_");
        String cypher = String.format("""
                MATCH (h:Entity {name: $head})
                MATCH (t:Entity {name: $tail})
                MERGE (h)-[r:%s]->(t)
                SET r.confidence = $conf, r.updated_at = timestamp()
                """, relType);
        try (Session session = driver.session()) {
            session.run(cypher, Map.of("head", relation.getHead(), "tail", relation.getTail(),
                    "conf", relation.getConfidence()));
        }
    }

    public List<QAResult.RetrievedContext> searchByQuestion(String question) {
        if (driver == null) return List.of();
        List<QAResult.RetrievedContext> results = new ArrayList<>();
        String cypher = """
                MATCH (e:Entity)
                WHERE e.name CONTAINS $keyword OR e.description CONTAINS $keyword
                OPTIONAL MATCH (e)-[r]-(neighbor:Entity)
                RETURN e.name AS entity, type(r) AS relation, neighbor.name AS neighbor
                LIMIT 20
                """;
        try (Session session = driver.session()) {
            String keyword = question.length() > 20 ? question.substring(0, 20) : question;
            var records = session.run(cypher, Map.of("keyword", keyword)).list();
            for (var record : records) {
                String content = record.get("entity").asString("") + " --["
                        + record.get("relation").asString("related") + "]--> "
                        + record.get("neighbor").asString("");
                results.add(QAResult.RetrievedContext.builder()
                        .content(content)
                        .source("knowledge_graph")
                        .score(0.8)
                        .retrievalType("graph")
                        .metadata(Map.of())
                        .build());
            }
        } catch (Exception e) {
            // graph not available
        }
        return results;
    }

    public void deleteBySource(String source) {
        if (driver == null) return;
        try (Session session = driver.session()) {
            session.run("MATCH (e:Entity {source: $source}) DETACH DELETE e", Map.of("source", source));
        }
    }

    public Map<String, Object> getStats() {
        if (driver == null) return Map.of("status", "disconnected");
        try (Session session = driver.session()) {
            long entities = session.run("MATCH (e:Entity) RETURN count(e) AS cnt")
                    .single().get("cnt").asLong();
            long relations = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt")
                    .single().get("cnt").asLong();
            return Map.of("totalEntities", entities, "totalRelations", relations);
        } catch (Exception e) {
            return Map.of("status", "error", "message", e.getMessage());
        }
    }
}
