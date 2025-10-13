package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"controller"
)

func main() {
	// Set up logging
	log.SetFlags(log.LstdFlags | log.Lshortfile)

	// Create lifecycle manager
	lifecycle := controller.NewLifecycle()

	// Start all components
	if err := lifecycle.Startup(); err != nil {
		log.Fatalf("Failed to start controller: %v", err)
	}

	// Set up signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	// Start API server in a goroutine
	go func() {
		if err := lifecycle.Run(); err != nil {
			log.Fatalf("API server failed: %v", err)
		}
	}()

	// Wait for shutdown signal
	sig := <-sigChan
	log.Printf("Received signal %v, shutting down gracefully...", sig)

	// Shutdown
	lifecycle.Shutdown()
	log.Println("Shutdown complete")
}
