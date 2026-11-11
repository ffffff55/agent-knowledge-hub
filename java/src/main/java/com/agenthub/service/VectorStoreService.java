package com.agenthub.service;

import com.agenthub.model.DocumentChunk;
import com.agenthub.model.QAResult;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 向量存储服务 (Java版)
 *
 * 生产环境可对接 Milvus / PGVector，
 * 这里提供内存实现以降低演示门槛。
 */
@Service
public class VectorStoreService {

    private final EmbeddingModel embeddingModel;
    private final Map<String, StoredVector> store = new ConcurrentHashMap<>();

    public VectorStoreService(EmbeddingModel embeddingModel) {
        this.embeddingModel = embeddingModel;
    }

    public void addChunks(List<DocumentChunk> chunks) {
        List<String> texts = chunks.stream().map(DocumentChunk::getContent).toList();
        var embeddings = embeddingModel.embed(texts);

        for (int i = 0; i < chunks.size(); i++) {
            DocumentChunk chunk = chunks.get(i);
            float[] vector = embeddings.get(i);
            store.put(chunk.getChunkId(), new StoredVector(
                    chunk.getChunkId(), chunk.getDocId(), chunk.getContent(),
                    chunk.getMetadata(), vector
            ));
        }
    }

    public List<QAResult.RetrievedContext> search(String query, int topK) {
        float[] queryVec = embeddingModel.embed(query);

        return store.values().stream()
                .map(sv -> Map.entry(sv, cosineSimilarity(queryVec, sv.vector)))
                .sorted((a, b) -> Double.compare(b.getValue(), a.getValue()))
                .limit(topK)
                .map(entry -> QAResult.RetrievedContext.builder()
                        .content(entry.getKey().content)
                        .source(String.valueOf(entry.getKey().metadata.getOrDefault("source", "vector_store")))
                        .score(entry.getValue())
                        .retrievalType("vector")
                        .metadata(entry.getKey().metadata)
                        .build())
                .toList();
    }

    public int deleteByDocId(String docId) {
        List<String> toDelete = store.entrySet().stream()
                .filter(e -> e.getValue().docId.equals(docId))
                .map(Map.Entry::getKey)
                .toList();
        toDelete.forEach(store::remove);
        return toDelete.size();
    }

    public Map<String, Object> getStats() {
        return Map.of("backend", "in-memory", "totalVectors", store.size());
    }

    private static double cosineSimilarity(float[] a, float[] b) {
        double dot = 0, normA = 0, normB = 0;
        for (int i = 0; i < Math.min(a.length, b.length); i++) {
            dot += a[i] * b[i];
            normA += a[i] * a[i];
            normB += b[i] * b[i];
        }
        return dot / (Math.sqrt(normA) * Math.sqrt(normB) + 1e-10);
    }

    private record StoredVector(String chunkId, String docId, String content,
                                 Map<String, Object> metadata, float[] vector) {}
}
