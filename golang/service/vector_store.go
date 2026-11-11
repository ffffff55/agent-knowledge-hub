package service

import (
	"context"
	"math"
	"sort"
	"sync"

	"github.com/bcefghj/agent-knowledge-hub/model"
)

// VectorStoreService 向量存储服务 (Go版)
//
// 生产环境对接 pgvector，此处提供内存实现降低演示门槛。
// Go 的并发安全通过 sync.RWMutex 保证。
type VectorStoreService struct {
	mu    sync.RWMutex
	store map[string]storedVector
}

type storedVector struct {
	ChunkID  string
	DocID    string
	Content  string
	Metadata map[string]interface{}
	Vector   []float32
}

func NewVectorStoreService() *VectorStoreService {
	return &VectorStoreService{store: make(map[string]storedVector)}
}

func (s *VectorStoreService) AddChunks(_ context.Context, chunks []model.DocumentChunk) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, c := range chunks {
		s.store[c.ChunkID] = storedVector{
			ChunkID:  c.ChunkID,
			DocID:    c.DocID,
			Content:  c.Content,
			Metadata: c.Metadata,
			Vector:   c.Embedding,
		}
	}
	return nil
}

func (s *VectorStoreService) Search(_ context.Context, query string, topK int) ([]model.RetrievedContext, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	type scored struct {
		sv    storedVector
		score float64
	}
	var results []scored
	for _, sv := range s.store {
		score := 0.5 // 简化: 无嵌入时使用默认分数
		if len(sv.Vector) > 0 {
			// 实际环境: 计算 query embedding 与 sv.Vector 的余弦相似度
			score = 0.7
		}
		results = append(results, scored{sv: sv, score: score})
	}

	sort.Slice(results, func(i, j int) bool { return results[i].score > results[j].score })
	if len(results) > topK {
		results = results[:topK]
	}

	var contexts []model.RetrievedContext
	for _, r := range results {
		source, _ := r.sv.Metadata["source"].(string)
		contexts = append(contexts, model.RetrievedContext{
			Content:       r.sv.Content,
			Source:        source,
			Score:         r.score,
			RetrievalType: "vector",
			Metadata:      r.sv.Metadata,
		})
	}
	return contexts, nil
}

func (s *VectorStoreService) DeleteByDocID(_ context.Context, docID string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	count := 0
	for k, v := range s.store {
		if v.DocID == docID {
			delete(s.store, k)
			count++
		}
	}
	return count
}

func (s *VectorStoreService) Stats() map[string]interface{} {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return map[string]interface{}{"backend": "in-memory", "totalVectors": len(s.store)}
}

func cosineSim(a, b []float32) float64 {
	if len(a) != len(b) || len(a) == 0 {
		return 0
	}
	var dot, na, nb float64
	for i := range a {
		dot += float64(a[i]) * float64(b[i])
		na += float64(a[i]) * float64(a[i])
		nb += float64(b[i]) * float64(b[i])
	}
	return dot / (math.Sqrt(na)*math.Sqrt(nb) + 1e-10)
}
