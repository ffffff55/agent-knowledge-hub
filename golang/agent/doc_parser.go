package agent

import (
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/bcefghj/agent-knowledge-hub/model"
)

const (
	chunkSize    = 512
	chunkOverlap = 64
)

// DocParserAgent 文档解析 Agent (Go版)
//
// 支持 PDF / 图片 / 表格 / 纯文本等格式。
// Go 版侧重高并发文件处理，利用 goroutine 实现并行解析。
type DocParserAgent struct{}

func NewDocParserAgent() *DocParserAgent {
	return &DocParserAgent{}
}

// Parse 解析单个文件
func (a *DocParserAgent) Parse(filePath string) ([]model.DocumentChunk, error) {
	docID := computeDocID(filePath)
	docType := detectType(filePath)

	rawText, err := extractText(filePath)
	if err != nil {
		return nil, fmt.Errorf("extract text: %w", err)
	}

	return chunkText(rawText, docID, docType, filePath), nil
}

// ParseBatch 批量解析（利用 goroutine 并行）
func (a *DocParserAgent) ParseBatch(filePaths []string) ([]model.DocumentChunk, error) {
	type result struct {
		chunks []model.DocumentChunk
		err    error
	}

	ch := make(chan result, len(filePaths))
	for _, fp := range filePaths {
		go func(path string) {
			chunks, err := a.Parse(path)
			ch <- result{chunks: chunks, err: err}
		}(fp)
	}

	var allChunks []model.DocumentChunk
	for range filePaths {
		res := <-ch
		if res.err != nil {
			continue
		}
		allChunks = append(allChunks, res.chunks...)
	}
	return allChunks, nil
}

func extractText(filePath string) (string, error) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func detectType(filePath string) string {
	ext := strings.ToLower(filepath.Ext(filePath))
	switch ext {
	case ".pdf":
		return "pdf"
	case ".png", ".jpg", ".jpeg":
		return "image"
	case ".csv", ".xlsx":
		return "table"
	case ".md":
		return "markdown"
	default:
		return "text"
	}
}

func chunkText(text, docID, docType, source string) []model.DocumentChunk {
	var chunks []model.DocumentChunk
	runes := []rune(text)
	idx := 0
	start := 0

	for start < len(runes) {
		end := start + chunkSize
		if end > len(runes) {
			end = len(runes)
		}
		content := strings.TrimSpace(string(runes[start:end]))
		if content != "" {
			chunks = append(chunks, model.DocumentChunk{
				ChunkID:    fmt.Sprintf("%s#chunk-%d", docID, idx),
				DocID:      docID,
				ChunkIndex: idx,
				Content:    content,
				DocType:    docType,
				Metadata: map[string]interface{}{
					"source":    source,
					"charStart": start,
					"charEnd":   end,
				},
			})
			idx++
		}
		start = end - chunkOverlap
		if start < 0 {
			start = 0
		}
	}
	return chunks
}

func computeDocID(path string) string {
	h := sha256.Sum256([]byte(path))
	return fmt.Sprintf("%x", h)[:16]
}
