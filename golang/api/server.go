package api

import (
	"net/http"

	"github.com/bcefghj/agent-knowledge-hub/agent"
	"github.com/bcefghj/agent-knowledge-hub/config"
	"github.com/bcefghj/agent-knowledge-hub/service"
	"github.com/gin-gonic/gin"
)

// Server HTTP API 服务器 (Go版)
type Server struct {
	cfg       *config.Config
	parser    *agent.DocParserAgent
	extractor *agent.KnowledgeExtractAgent
	qa        *agent.QAAgent
	vs        *service.VectorStoreService
	kg        *service.KnowledgeGraphService
}

func NewServer(cfg *config.Config, vs *service.VectorStoreService, kg *service.KnowledgeGraphService) *Server {
	parser := agent.NewDocParserAgent()
	extractor := agent.NewKnowledgeExtractAgent(cfg)
	qa := agent.NewQAAgent(cfg, vs, kg)

	return &Server{
		cfg: cfg, parser: parser, extractor: extractor, qa: qa, vs: vs, kg: kg,
	}
}

func (s *Server) Run() error {
	r := gin.Default()

	r.POST("/api/ingest/upload", s.handleUpload)
	r.POST("/api/qa/ask", s.handleAsk)
	r.GET("/api/admin/stats", s.handleStats)
	r.GET("/api/health", s.handleHealth)

	return r.Run(":" + s.cfg.APIPort)
}

func (s *Server) handleUpload(c *gin.Context) {
	file, err := c.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	savePath := "./uploads/" + file.Filename
	if err := c.SaveUploadedFile(file, savePath); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	chunks, err := s.parser.Parse(savePath)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	_ = s.vs.AddChunks(c.Request.Context(), chunks)

	extractions, _ := s.extractor.Extract(c.Request.Context(), chunks)
	entityCount, relCount := 0, 0
	for _, ext := range extractions {
		for _, ent := range ext.Entities {
			_ = s.kg.UpsertEntity(c.Request.Context(), ent)
			entityCount++
		}
		for _, rel := range ext.Relations {
			_ = s.kg.AddRelation(c.Request.Context(), rel)
			relCount++
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"fileName":  file.Filename,
		"chunks":    len(chunks),
		"entities":  entityCount,
		"relations": relCount,
		"status":    "success",
	})
}

func (s *Server) handleAsk(c *gin.Context) {
	var req struct {
		Question string `json:"question"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	result, err := s.qa.Answer(c.Request.Context(), req.Question)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, result)
}

func (s *Server) handleStats(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"vectorStore":    s.vs.Stats(),
		"knowledgeGraph": s.kg.Stats(c.Request.Context()),
	})
}

func (s *Server) handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "AgentKnowledgeHub-Go"})
}
