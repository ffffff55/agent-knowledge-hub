package com.agenthub.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ExtractionResult {
    private List<Entity> entities;
    private List<Relation> relations;
    private String sourceChunkId;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Entity {
        private String name;
        private String type;
        private String description;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Relation {
        private String head;
        private String relation;
        private String tail;
        private double confidence;
    }
}
