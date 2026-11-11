package model

// DocumentChunk 文档块
type DocumentChunk struct {
	ChunkID    string                 `json:"chunk_id"`
	DocID      string                 `json:"doc_id"`
	ChunkIndex int                    `json:"chunk_index"`
	Content    string                 `json:"content"`
	DocType    string                 `json:"doc_type"`
	Metadata   map[string]interface{} `json:"metadata"`
	Embedding  []float32              `json:"embedding,omitempty"`
}

// Entity 知识实体
type Entity struct {
	Name        string `json:"name"`
	Type        string `json:"type"`
	Description string `json:"description"`
}

// Relation 知识关系
type Relation struct {
	Head       string  `json:"head"`
	Relation   string  `json:"relation"`
	Tail       string  `json:"tail"`
	Confidence float64 `json:"confidence"`
}

// ExtractionResult 知识抽取结果
type ExtractionResult struct {
	Entities      []Entity  `json:"entities"`
	Relations     []Relation `json:"relations"`
	SourceChunkID string    `json:"source_chunk_id"`
}

// RetrievedContext 检索上下文
type RetrievedContext struct {
	Content       string                 `json:"content"`
	Source        string                 `json:"source"`
	Score         float64                `json:"score"`
	RetrievalType string                 `json:"retrieval_type"`
	Metadata      map[string]interface{} `json:"metadata,omitempty"`
}

// QAResult 问答结果
type QAResult struct {
	Question       string             `json:"question"`
	Answer         string             `json:"answer"`
	Confidence     float64            `json:"confidence"`
	Intent         string             `json:"intent"`
	Contexts       []RetrievedContext  `json:"contexts"`
	ReasoningSteps []string           `json:"reasoning_steps"`
}

// CDCEvent 变更事件
type CDCEvent struct {
	FilePath   string `json:"file_path"`
	ChangeType string `json:"change_type"`
}
