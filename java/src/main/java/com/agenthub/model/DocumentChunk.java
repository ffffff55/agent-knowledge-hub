package com.agenthub.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DocumentChunk {
    private String chunkId;
    private String docId;
    private int chunkIndex;
    private String content;
    private String docType;
    private Map<String, Object> metadata;
    private float[] embedding;
}
