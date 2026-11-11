package service

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/bcefghj/agent-knowledge-hub/config"
	"github.com/bcefghj/agent-knowledge-hub/model"
	"github.com/neo4j/neo4j-go-driver/v5/neo4j"
)

// KnowledgeGraphService 知识图谱服务 (Go版)
//
// 使用 Neo4j Go Driver 管理知识图谱
type KnowledgeGraphService struct {
	driver neo4j.DriverWithContext
}

func NewKnowledgeGraphService(cfg *config.Config) (*KnowledgeGraphService, error) {
	driver, err := neo4j.NewDriverWithContext(cfg.Neo4jURI, neo4j.BasicAuth(cfg.Neo4jUser, cfg.Neo4jPassword, ""))
	if err != nil {
		return nil, fmt.Errorf("neo4j connect: %w", err)
	}
	svc := &KnowledgeGraphService{driver: driver}
	svc.ensureIndexes(context.Background())
	return svc, nil
}

func (s *KnowledgeGraphService) Close(ctx context.Context) {
	if s.driver != nil {
		_ = s.driver.Close(ctx)
	}
}

func (s *KnowledgeGraphService) ensureIndexes(ctx context.Context) {
	session := s.driver.NewSession(ctx, neo4j.SessionConfig{})
	defer session.Close(ctx)
	queries := []string{
		"CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.name)",
		"CREATE INDEX IF NOT EXISTS FOR (n:Entity) ON (n.type)",
	}
	for _, q := range queries {
		_, _ = session.Run(ctx, q, nil)
	}
}

// UpsertEntity 创建或更新实体
func (s *KnowledgeGraphService) UpsertEntity(ctx context.Context, entity model.Entity) error {
	session := s.driver.NewSession(ctx, neo4j.SessionConfig{})
	defer session.Close(ctx)

	cypher := `
	MERGE (e:Entity {name: $name})
	ON CREATE SET e.type = $type, e.description = $desc, e.created_at = $now
	ON MATCH SET e.description = CASE WHEN $desc <> '' THEN $desc ELSE e.description END, e.updated_at = $now
	`
	_, err := session.Run(ctx, cypher, map[string]interface{}{
		"name": entity.Name, "type": entity.Type, "desc": entity.Description,
		"now": time.Now().Unix(),
	})
	return err
}

// AddRelation 创建关系
func (s *KnowledgeGraphService) AddRelation(ctx context.Context, rel model.Relation) error {
	session := s.driver.NewSession(ctx, neo4j.SessionConfig{})
	defer session.Close(ctx)

	relType := strings.ToUpper(strings.ReplaceAll(rel.Relation, " ", "_"))
	cypher := fmt.Sprintf(`
	MATCH (h:Entity {name: $head})
	MATCH (t:Entity {name: $tail})
	MERGE (h)-[r:%s]->(t)
	SET r.confidence = $conf, r.updated_at = $now
	`, relType)
	_, err := session.Run(ctx, cypher, map[string]interface{}{
		"head": rel.Head, "tail": rel.Tail, "conf": rel.Confidence,
		"now": time.Now().Unix(),
	})
	return err
}

// SearchByKeyword 关键词搜索实体及关系
func (s *KnowledgeGraphService) SearchByKeyword(ctx context.Context, keyword string) ([]model.RetrievedContext, error) {
	session := s.driver.NewSession(ctx, neo4j.SessionConfig{})
	defer session.Close(ctx)

	if len(keyword) > 20 {
		keyword = keyword[:20]
	}

	cypher := `
	MATCH (e:Entity)
	WHERE e.name CONTAINS $keyword OR e.description CONTAINS $keyword
	OPTIONAL MATCH (e)-[r]-(neighbor:Entity)
	RETURN e.name AS entity, type(r) AS relation, neighbor.name AS neighbor
	LIMIT 20
	`
	result, err := session.Run(ctx, cypher, map[string]interface{}{"keyword": keyword})
	if err != nil {
		return nil, err
	}

	var contexts []model.RetrievedContext
	for result.Next(ctx) {
		record := result.Record()
		entityVal, _ := record.Get("entity")
		relVal, _ := record.Get("relation")
		neighborVal, _ := record.Get("neighbor")

		content := fmt.Sprintf("%v --[%v]--> %v", entityVal, relVal, neighborVal)
		contexts = append(contexts, model.RetrievedContext{
			Content:       content,
			Source:        "knowledge_graph",
			Score:         0.8,
			RetrievalType: "graph",
		})
	}
	return contexts, nil
}

// DeleteBySource 按来源删除
func (s *KnowledgeGraphService) DeleteBySource(ctx context.Context, source string) error {
	session := s.driver.NewSession(ctx, neo4j.SessionConfig{})
	defer session.Close(ctx)
	_, err := session.Run(ctx, "MATCH (e:Entity {source: $source}) DETACH DELETE e",
		map[string]interface{}{"source": source})
	return err
}

// Stats 统计信息
func (s *KnowledgeGraphService) Stats(ctx context.Context) map[string]interface{} {
	session := s.driver.NewSession(ctx, neo4j.SessionConfig{})
	defer session.Close(ctx)

	result := map[string]interface{}{"status": "ok"}
	r1, err := session.Run(ctx, "MATCH (e:Entity) RETURN count(e) AS cnt", nil)
	if err == nil && r1.Next(ctx) {
		cnt, _ := r1.Record().Get("cnt")
		result["totalEntities"] = cnt
	}
	r2, err := session.Run(ctx, "MATCH ()-[r]->() RETURN count(r) AS cnt", nil)
	if err == nil && r2.Next(ctx) {
		cnt, _ := r2.Record().Get("cnt")
		result["totalRelations"] = cnt
	}
	return result
}
