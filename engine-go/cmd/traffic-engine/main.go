package main

import (
	"os"
	"os/signal"
	"syscall"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/unoc/engine-go/internal/api"
	"github.com/unoc/engine-go/internal/config"
	"github.com/unoc/engine-go/internal/db"
)

func main() {
	// Setup structured logging
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout})

	log.Info().Msg("Starting UNOC Traffic Engine (Go)")

	// Load configuration
	cfg := config.Load()
	log.Info().
		Str("environment", cfg.Environment).
		Str("port", cfg.Port).
		Msg("Configuration loaded")

	// Cap log volume after startup messages: per-tick logging at info/debug
	// grew logs by hundreds of MB per day. Override via LOG_LEVEL if needed.
	levelStr := os.Getenv("LOG_LEVEL")
	if levelStr == "" {
		levelStr = "warn"
	}
	if lvl, err := zerolog.ParseLevel(levelStr); err == nil {
		zerolog.SetGlobalLevel(lvl)
	} else {
		log.Warn().Str("LOG_LEVEL", levelStr).Msg("Unknown log level, keeping default")
	}

	// Connect to PostgreSQL
	if err := db.Connect(cfg.DatabaseURL); err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to database")
	}
	defer db.Close()

	// Create HTTP server
	server := api.NewServer()

	// Handle graceful shutdown
	go func() {
		if err := server.Run(cfg.Port); err != nil {
			log.Fatal().Err(err).Msg("Failed to start HTTP server")
		}
	}()

	// Wait for interrupt signal
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info().Msg("Shutting down UNOC Traffic Engine")
}
