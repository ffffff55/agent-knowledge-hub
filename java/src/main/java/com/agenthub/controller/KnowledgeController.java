package com.agenthub.controller;

import com.agenthub.agent.DocParserAgent;
import com.agenthub.agent.KnowledgeExtractAgent;
import com.agenthub.agent.KnowledgeUpdateAgent;
import com.agenthub.agent.QAAgent;
import com.agenthub.model.DocumentChunk;
import com.agenthub.model.ExtractionResult;
import com.agenthub.model.QAResult;
import com.agenthub.service.KnowledgeGraphService;
import com.agenthub.service.VectorStoreService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

/**
 * REST API 控制器 (Java版)
 */
@RestController
@RequestMapping("/api")
public class KnowledgeController {

    private final DocParserAgent docParser;
    private final KnowledgeExtractAgent extractor;
    private final QAAgent qaAgent;
    private final KnowledgeUpdateAgent updateAgent;
    private final VectorStoreService vectorStore;
    private final KnowledgeGraphService knowledgeGraph;

    public KnowledgeController(DocParserAgent docParser, KnowledgeExtractAgent extractor,
                                QAAgent qaAgent, KnowledgeUpdateAgent updateAgent,
                                VectorStoreService vectorStore, KnowledgeGraphService knowledgeGraph) {
        this.docParser = docParser;
        this.extractor = extractor;
        this.qaAgent = qaAgent;
        this.updateAgent = updateAgent;
        this.vectorStore = vectorStore;
        this.knowledgeGraph = knowledgeGraph;
    }

    @PostMapping("/ingest/upload")
    public ResponseEntity<Map<String, Object>> upload(@RequestParam("file") MultipartFile file) throws Exception {
        Path tempDir = Files.createTempDirectory("uploads");
        File saved = tempDir.resolve(file.getOriginalFilename()).toFile();
        file.transferTo(saved);

        List<DocumentChunk> chunks = docParser.parse(saved.getAbsolutePath());
        vectorStore.addChunks(chunks);

        List<ExtractionResult> extractions = extractor.extract(chunks);
        int entityCount = 0, relCount = 0;
        for (ExtractionResult ext : extractions) {
            for (ExtractionResult.Entity e : ext.getEntities()) {
                knowledgeGraph.upsertEntity(e);
                entityCount++;
            }
            for (ExtractionResult.Relation r : ext.getRelations()) {
                knowledgeGraph.addRelation(r);
                relCount++;
            }
        }

        return ResponseEntity.ok(Map.of(
                "fileName", file.getOriginalFilename(),
                "chunks", chunks.size(),
                "entities", entityCount,
                "relations", relCount,
                "status", "success"
        ));
    }

    @PostMapping("/qa/ask")
    public ResponseEntity<QAResult> ask(@RequestBody Map<String, String> body) {
        String question = body.getOrDefault("question", "");
        QAResult result = qaAgent.answer(question);
        return ResponseEntity.ok(result);
    }

    @GetMapping("/admin/stats")
    public ResponseEntity<Map<String, Object>> stats() {
        return ResponseEntity.ok(Map.of(
                "vectorStore", vectorStore.getStats(),
                "knowledgeGraph", knowledgeGraph.getStats()
        ));
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of("status", "ok", "service", "AgentKnowledgeHub-Java"));
    }
}
