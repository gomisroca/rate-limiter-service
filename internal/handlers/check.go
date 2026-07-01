package handlers

import (
	"encoding/json"
	"math"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type RateLimiter interface {
	Allow(key string, cost float64) (allowed bool, remaining int, limit int, retryAfter time.Duration)
}

type CheckResponse struct {
	Allowed 			bool 			`json:"allowed"`
	Limit 				int 			`json:"limit"`
	Remaining			int 			`json:"remaining"`
	ResetAfterSeconds 	float64 	`json:"resetAfterSeconds"`
}

type CheckHandler struct {
	Limiter RateLimiter
}

func NewCheckHandler(l RateLimiter) *CheckHandler {
	return &CheckHandler{Limiter: l}
}

// optional JSON body for POST /check
type checkRequestBody struct {
	Key  string  `json:"key,omitempty"`
	Cost float64 `json:"cost,omitempty"`
}

func (h *CheckHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var key string
	cost := 1.0

	switch r.Method {
	case http.MethodGet:
		key = r.URL.Query().Get("key")
		if c := r.URL.Query().Get("cost"); c != "" {
			if parsed, err := strconv.ParseFloat(c, 64); err == nil && parsed > 0 {
				cost = parsed
			}
		}
	case http.MethodPost:
		var body checkRequestBody
		if r.ContentLength != 0 {
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				writeError(w, http.StatusBadRequest, "Invalid request body: "+err.Error())
				return
			}
		}
		key = body.Key
		if body.Cost > 0 {
			cost = body.Cost
		}
	default:
		writeError(w, http.StatusMethodNotAllowed, "Only GET and POST methods are supported")
		return
	}

	if key == "" {
		key = clientIP(r)
	}

	allowed, remaining, limit, retryAfter := h.Limiter.Allow(key, cost)

	w.Header().Set("X-RateLimit-Limit", strconv.Itoa(limit))
	w.Header().Set("X-RateLimit-Remaining", strconv.Itoa(remaining))

	status := http.StatusOK
	if !allowed {
		status = http.StatusTooManyRequests
		w.Header().Set("Retry-After", strconv.Itoa(int(math.Ceil(retryAfter.Seconds()))))
	}

	writeJSON(w, status, CheckResponse{
		Allowed: allowed,
		Limit: limit,
		Remaining: remaining,
		ResetAfterSeconds: roundSeconds(retryAfter),
	})
}

func roundSeconds(d time.Duration) float64 {
	return math.Round(d.Seconds()*1000) / 1000
}

// Extract client id when no key is provided
func clientIP(r *http.Request) string {
	if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
		if before, _, ok := strings.Cut(fwd, ","); ok {
			return strings.TrimSpace(before)
		}
		return strings.TrimSpace(fwd)
	}
	
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}