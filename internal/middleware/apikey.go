package middleware

import (
	"crypto/subtle"
	"net/http"
)

// Requests must present a matching value in the X-API-Key header
func RequireAPIKey(apiKey string, next http.Handler) http.Handler {
	if apiKey == "" {
		return next
	}

	expected := []byte(apiKey)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		provided := []byte(r.Header.Get("X-API-Key"))

		if len(provided) != len(expected) || subtle.ConstantTimeCompare(provided, expected) != 1 {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(`{"error":"missing or invalid API key"}`))
			return
		}
		next.ServeHTTP(w, r)
	})
}
