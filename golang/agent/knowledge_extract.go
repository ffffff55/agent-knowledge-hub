package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/bcefghj/agent-knowledge-hub/config"
	"github.com/bcefghj/agent-knowledge-hub/model"
	openai "github.com/sashabaranov/go-openai"
)

const extractionPrompt = `你是一个专业的知识抽取引擎。给定一段文本，请提取实体和关系。
返回 JSON 格式:
{
  "entities": [{"name": "实体名", "type": "类型", "description": "描述"}],
  "relations": [{"head": "头实体", "relation": "关系", "tail": "尾实体", "confidence": 0.95}]
}
只返回 JSON。`

// KnowledgeExtractAgent 知识抽取 Agent (Go版)
type KnowledgeExtractAgent struct {
	client *openai.Client
	model  string
}

func NewKnowledgeExtractAgent(cfg *config.Config) *KnowledgeExtractAgent {
	clientConfig := openai.DefaultConfig(cfg.OpenAIKey)
	clientConfig.BaseURL = cfg.OpenAIBaseURL
	return &KnowledgeExtractAgent{
		client: openai.NewClientWithConfig(clientConfig),
		model:  cfg.OpenAIModel,
	}
}

// Extract 从文档块中抽取知识
func (a *KnowledgeExtractAgent) Extract(ctx context.Context, chunks []model.DocumentChunk) ([]model.ExtractionResult, error) {
	seenEntities := make(map[string]bool)
	seenRelations := make(map[string]bool)
	var results []model.ExtractionResult

	for _, chunk := range chunks {
		result, err := a.extractFromChunk(ctx, chunk)
		if err != nil {
			continue
		}
		deduplicate(result, seenEntities, seenRelations)
		results = append(results, *result)
	}
	return results, nil
}

func (a *KnowledgeExtractAgent) extractFromChunk(ctx context.Context, chunk model.DocumentChunk) (*model.ExtractionResult, error) {
	resp, err := a.client.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
		Model: a.model,
		Messages: []openai.ChatCompletionMessage{
			{Role: openai.ChatMessageRoleSystem, Content: extractionPrompt},
			{Role: openai.ChatMessageRoleUser, Content: "请从以下文本中抽取知识：\n\n" + chunk.Content},
		},
		Temperature: 0,
	})
	if err != nil {
		return nil, fmt.Errorf("LLM call failed: %w", err)
	}

	raw := resp.Choices[0].Message.Content
	return parseExtractionResponse(raw, chunk.ChunkID)
}

func parseExtractionResponse(raw, sourceID string) (*model.ExtractionResult, error) {
	cleaned := strings.TrimSpace(raw)
	if strings.HasPrefix(cleaned, "```") {
		parts := strings.SplitN(cleaned, "\n", 2)
		if len(parts) == 2 {
			cleaned = parts[1]
		}
		if idx := strings.LastIndex(cleaned, "```"); idx >= 0 {
			cleaned = cleaned[:idx]
		}
	}

	var data struct {
		Entities  []model.Entity  `json:"entities"`
		Relations []model.Relation `json:"relations"`
	}
	if err := json.Unmarshal([]byte(cleaned), &data); err != nil {
		return &model.ExtractionResult{SourceChunkID: sourceID}, nil
	}

	return &model.ExtractionResult{
		Entities:      data.Entities,
		Relations:     data.Relations,
		SourceChunkID: sourceID,
	}, nil
}

func deduplicate(result *model.ExtractionResult, seenE map[string]bool, seenR map[string]bool) {
	var uniqueEntities []model.Entity
	for _, e := range result.Entities {
		key := e.Name + "::" + e.Type
		if !seenE[key] {
			seenE[key] = true
			uniqueEntities = append(uniqueEntities, e)
		}
	}
	result.Entities = uniqueEntities

	var uniqueRelations []model.Relation
	for _, r := range result.Relations {
		key := r.Head + "::" + r.Relation + "::" + r.Tail
		if !seenR[key] {
			seenR[key] = true
			uniqueRelations = append(uniqueRelations, r)
		}
	}
	result.Relations = uniqueRelations
}
