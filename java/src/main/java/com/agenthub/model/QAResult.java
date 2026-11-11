package com.agenthub.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class QAResult {
    private String question;
    private String answer;
    private double confidence;
    private String intent;
    private List<RetrievedContext> contexts;
    private List<String> reasoningSteps;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RetrievedContext {
        private String content;
        private String source;
        private double score;
        private String retrievalType;
        private Map<String, Object> metadata;
    }
}
