package main

import (
	"context"
	"log"
	"net/http"
	"os/signal"
	"rate-limiter/internal/config"
	"rate-limiter/internal/handlers"
	"rate-limiter/internal/limiter"
	"rate-limiter/internal/middleware"
	"syscall"
	"time"
)

func main() {
	cfg := config.Load()

	lim := limiter.New(cfg.Capacity, cfg.Window, cfg.IdleTTL)

	// Cancel the cleanup goroutine on SIGINT/SIGTERM
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	lim.StartCleanup(ctx, cfg.CleanupInterval)

	checkHandler := handlers.NewCheckHandler(lim)

	if cfg.APIKey == "" {
		log.Println("WARNING: API_KEY is not set - '/check' is open to anyone who can reach this service.")
	}

	mux := http.NewServeMux()

	mux.HandleFunc("GET /health", handlers.Health)
	mux.Handle("GET /check", middleware.RequireAPIKey(cfg.APIKey, checkHandler))
	mux.Handle("POST /check", middleware.RequireAPIKey(cfg.APIKey, checkHandler))
	// Test page
	mux.Handle("GET /", http.FileServer(http.Dir("./web")))
	
	srv := &http.Server{
		Addr:         ":" + cfg.Port,
		Handler:      withCORS(mux),
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	log.Printf("Rate limiter service listening on :%s (capacity=%d per %s)", cfg.Port, cfg.Capacity, cfg.Window)
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
