package agent

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/bcefghj/agent-knowledge-hub/config"
	"github.com/bcefghj/agent-knowledge-hub/model"
	"github.com/bcefghj/agent-knowledge-hub/service"
	openai "github.com/sashabaranov/go-openai"
)

const answerPrompt = `你是一个专业的企业知识问答助手。根据检索到的上下文信息回答用户问题。
要求：答案必须基于上下文，引用来源，如果信息不足请告知用户。`

// QAAgent 问答 Agent (Go版)
//
// 实现 GraphRAG 混合检索:
//   - 向量语义检索 (pgvector)
//   - 知识图谱检索 (Neo4j)
//   - 混合重排序 + LLM 答案生成
type QAAgent struct {
	client *openai.Client
	model  string
	vs     *service.VectorStoreService
	kg     *service.KnowledgeGraphService
}

func NewQAAgent(cfg *config.Config, vs *service.VectorStoreService, kg *service.KnowledgeGraphService) *QAAgent {
	clientConfig := openai.DefaultConfig(cfg.OpenAIKey)
	clientConfig.BaseURL = cfg.OpenAIBaseURL
	return &QAAgent{
		client: openai.NewClientWithConfig(clientConfig),
		model:  cfg.OpenAIModel,
		vs:     vs,
		kg:     kg,
	}
}

// Answer 完整问答流程
func (a *QAAgent) Answer(ctx context.Context, question string) (*model.QAResult, error) {
	reasoning := []string{}

	// 向量检索
	vectorCtx, _ := a.vs.Search(ctx, question, 5)
	reasoning = append(reasoning, fmt.Sprintf("向量检索: %d 条结果", len(vectorCtx)))

	// 图谱检索
	graphCtx, _ := a.kg.SearchByKeyword(ctx, question)
	reasoning = append(reasoning, fmt.Sprintf("图谱检索: %d 条结果", len(graphCtx)))

	// 混合重排序
	merged := hybridRerank(vectorCtx, graphCtx)
	topK := 8
	if len(merged) < topK {
		topK = len(merged)
	}
	topCtx := merged[:topK]

	// 生成答案
	answer, err := a.generateAnswer(ctx, question, topCtx)
	if err != nil {
		return nil, err
	}
	reasoning = append(reasoning, "答案生成完成")

	confidence := 0.0
	for _, c := range topCtx {
		confidence += c.Score
	}
	if len(topCtx) > 0 {
		confidence /= float64(len(topCtx))
	}

	return &model.QAResult{
		Question:       question,
		Answer:         answer,
		Confidence:     confidence,
		Intent:         "factoid",
		Contexts:       topCtx,
		ReasoningSteps: reasoning,
	}, nil
}

func hybridRerank(vector, graph []model.RetrievedContext) []model.RetrievedContext {
	var all []model.RetrievedContext
	for _, c := range vector {
		c.Score *= 1.0
		all = append(all, c)
	}
	for _, c := range graph {
		c.Score *= 1.2
		all = append(all, c)
	}
	sort.Slice(all, func(i, j int) bool { return all[i].Score > all[j].Score })
	return all
}

func (a *QAAgent) generateAnswer(ctx context.Context, question string, contexts []model.RetrievedContext) (string, error) {
	var sb strings.Builder
	for i, c := range contexts {
		sb.WriteString(fmt.Sprintf("[来源 %d: %s | 分数: %.2f]\n%s\n\n", i+1, c.Source, c.Score, c.Content))
	}

	resp, err := a.client.CreateChatCompletion(ctx, openai.ChatCompletionRequest{
		Model: a.model,
		Messages: []openai.ChatCompletionMessage{
			{Role: openai.ChatMessageRoleSystem, Content: answerPrompt},
			{Role: openai.ChatMessageRoleUser, Content: "上下文:\n" + sb.String() + "\n\n问题: " + question},
		},
		Temperature: 0,
	})
	if err != nil {
		return "", err
	}
	return resp.Choices[0].Message.Content, nil
}
