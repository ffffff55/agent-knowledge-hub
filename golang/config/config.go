package config

import "os"

// Config 全局配置，从环境变量加载
type Config struct {
	OpenAIKey      string
	OpenAIBaseURL  string
	OpenAIModel    string
	EmbeddingModel string

	Neo4jURI      string
	Neo4jUser     string
	Neo4jPassword string

	PgDSN string

	KafkaBrokers string
	KafkaTopic   string

	APIPort string
}

func Load() *Config {
	return &Config{
		OpenAIKey:      getEnv("OPENAI_API_KEY", ""),
		OpenAIBaseURL:  getEnv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
		OpenAIModel:    getEnv("OPENAI_MODEL", "gpt-4o"),
		EmbeddingModel: getEnv("EMBEDDING_MODEL", "text-embedding-3-small"),
		Neo4jURI:       getEnv("NEO4J_URI", "bolt://localhost:7687"),
		Neo4jUser:      getEnv("NEO4J_USER", "neo4j"),
		Neo4jPassword:  getEnv("NEO4J_PASSWORD", "password"),
		PgDSN:          getEnv("PG_DSN", "postgres://postgres:postgres@localhost:5432/knowledge?sslmode=disable"),
		KafkaBrokers:   getEnv("KAFKA_BROKERS", "localhost:9092"),
		KafkaTopic:     getEnv("KAFKA_TOPIC", "doc-changes"),
		APIPort:        getEnv("API_PORT", "8082"),
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
