package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	Port string

	// If left empty, the endpoint is open
	APIKey string

	// Capacity is the max number of tokens (i.e. requests) a single key can have available at once
	Capacity int
	Window   time.Duration

	// IdleTTL/CleanupInterval control memory reclamation
	IdleTTL         time.Duration
	CleanupInterval time.Duration
}

func Load() Config {
	return Config{
		Port:            getEnv("PORT", "8080"),
		APIKey:          getEnv("API_KEY", ""),
		Capacity:        int(getEnvInt64("RATE_LIMIT_CAPACITY", 100)),
		Window:          time.Duration(getEnvInt64("RATE_LIMIT_WINDOW_SECONDS", 60)) * time.Second,
		IdleTTL:         time.Duration(getEnvInt64("BUCKET_IDLE_TTL_SECONDS", 600)) * time.Second,
		CleanupInterval: time.Duration(getEnvInt64("CLEANUP_INTERVAL_SECONDS", 60)) * time.Second,
	}
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getEnvInt64(key string, fallback int64) int64 {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return n
		}
	}
	return fallback
}
