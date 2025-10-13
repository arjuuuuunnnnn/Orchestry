package controller

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"
)

type HealthCheckConfig struct {
	Path             string
	IntervalSeconds  int
	TimeoutSeconds   int
	FailureThreshold int
	SuccessThreshold int
}

type HealthStatus struct {
	IsHealthy           bool
	ConsecutiveFailures int
	ConsecutiveSuccess  int
	LastCheck           time.Time
	LastSuccess         time.Time
	ResponseTimeMS      float64
}

type ContainerInfo struct {
	IP   string
	Port int
}

type HealthChecker struct {
	mu            sync.Mutex
	healthConfigs map[string]HealthCheckConfig
	healthStatus  map[string]*HealthStatus
	containerInfo map[string]ContainerInfo
	running       bool
	callback      func(containerID string, healthy bool)
	wg            sync.WaitGroup
	ctx           context.Context
	cancel        context.CancelFunc
	client        *http.Client
}

// NewHealthChecker creates a new health checker
func NewHealthChecker() *HealthChecker {
	ctx, cancel := context.WithCancel(context.Background())
	return &HealthChecker{
		healthConfigs: make(map[string]HealthCheckConfig),
		healthStatus:  make(map[string]*HealthStatus),
		containerInfo: make(map[string]ContainerInfo),
		ctx:           ctx,
		cancel:        cancel,
		client: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// SetHealthChangeCallback sets a callback function when a container health status changes
func (hc *HealthChecker) SetHealthChangeCallback(cb func(string, bool)) {
	hc.callback = cb
}

// AddTarget adds a new container for health monitoring
func (hc *HealthChecker) AddTarget(containerID, ip string, port int, cfg HealthCheckConfig) {
	hc.mu.Lock()
	defer hc.mu.Unlock()

	if cfg.Path == "" {
		cfg.Path = "/healthz"
	}
	if cfg.IntervalSeconds == 0 {
		cfg.IntervalSeconds = 5
	}
	if cfg.TimeoutSeconds == 0 {
		cfg.TimeoutSeconds = 2
	}
	if cfg.FailureThreshold == 0 {
		cfg.FailureThreshold = 3
	}
	if cfg.SuccessThreshold == 0 {
		cfg.SuccessThreshold = 1
	}

	hc.healthConfigs[containerID] = cfg
	hc.healthStatus[containerID] = &HealthStatus{IsHealthy: false}
	hc.containerInfo[containerID] = ContainerInfo{IP: ip, Port: port}

	log.Printf("Added health check target: %s:%d for container %s", ip, port, containerID)
}

// RemoveTarget removes a container from health monitoring
func (hc *HealthChecker) RemoveTarget(containerID string) {
	hc.mu.Lock()
	defer hc.mu.Unlock()

	delete(hc.healthConfigs, containerID)
	delete(hc.healthStatus, containerID)
	delete(hc.containerInfo, containerID)
	log.Printf("Removed health check target: %s", containerID)
}

// IsHealthy returns whether a container is healthy
func (hc *HealthChecker) IsHealthy(containerID string) bool {
	hc.mu.Lock()
	defer hc.mu.Unlock()

	if status, ok := hc.healthStatus[containerID]; ok {
		return status.IsHealthy
	}
	return false
}

// Start begins the health checking loop in background goroutines
func (hc *HealthChecker) Start() {
	if hc.running {
		return
	}
	hc.running = true
	hc.wg.Add(1)
	go hc.loop()
	log.Println("Health checker started")
}

// Stop stops the health checking
func (hc *HealthChecker) Stop() {
	hc.cancel()
	hc.wg.Wait()
	hc.running = false
	log.Println("Health checker stopped")
}

// loop runs continuous health checks
func (hc *HealthChecker) loop() {
	defer hc.wg.Done()

	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-hc.ctx.Done():
			return
		case <-ticker.C:
			hc.runChecks()
		}
	}
}

// runChecks launches concurrent health checks for all containers
func (hc *HealthChecker) runChecks() {
	hc.mu.Lock()
	ids := make([]string, 0, len(hc.healthConfigs))
	for id := range hc.healthConfigs {
		ids = append(ids, id)
	}
	hc.mu.Unlock()

	var wg sync.WaitGroup
	for _, id := range ids {
		wg.Add(1)
		go func(cid string) {
			defer wg.Done()
			hc.checkContainer(cid)
		}(id)
	}
	wg.Wait()
}

// checkContainer performs health check for a single container
func (hc *HealthChecker) checkContainer(containerID string) {
	hc.mu.Lock()
	cfg, cfgOk := hc.healthConfigs[containerID]
	status, stOk := hc.healthStatus[containerID]
	info, infoOk := hc.containerInfo[containerID]
	hc.mu.Unlock()

	if !cfgOk || !stOk || !infoOk {
		return
	}

	now := time.Now()
	if now.Sub(status.LastCheck) < time.Duration(cfg.IntervalSeconds)*time.Second {
		return
	}

	status.LastCheck = now

	start := time.Now()
	healthy := hc.performHTTPCheck(info, cfg)
	elapsed := time.Since(start).Milliseconds()
	status.ResponseTimeMS = float64(elapsed)

	if healthy {
		status.ConsecutiveSuccess++
		status.ConsecutiveFailures = 0
		status.LastSuccess = now
		if !status.IsHealthy && status.ConsecutiveSuccess >= cfg.SuccessThreshold {
			status.IsHealthy = true
			log.Printf("Container %s is now healthy", containerID)
			if hc.callback != nil {
				hc.callback(containerID, true)
			}
		}
	} else {
		status.ConsecutiveFailures++
		status.ConsecutiveSuccess = 0
		if status.IsHealthy && status.ConsecutiveFailures >= cfg.FailureThreshold {
			status.IsHealthy = false
			log.Printf("Container %s is now unhealthy", containerID)
			if hc.callback != nil {
				hc.callback(containerID, false)
			}
		}
	}
}

// performHTTPCheck performs an HTTP GET and returns true if response is 2xx–3xx
func (hc *HealthChecker) performHTTPCheck(info ContainerInfo, cfg HealthCheckConfig) bool {
	url := fmt.Sprintf("http://%s:%d%s", info.IP, info.Port, cfg.Path)
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.TimeoutSeconds)*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		log.Printf("Error creating request: %v", err)
		return false
	}

	resp, err := hc.client.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()

	return resp.StatusCode >= 200 && resp.StatusCode < 400
}

// GetHealthStatus returns the current health status of a container
func (hc *HealthChecker) GetHealthStatus(containerID string) *HealthStatus {
	hc.mu.Lock()
	defer hc.mu.Unlock()
	return hc.healthStatus[containerID]
}

// GetAllHealthyContainers returns all healthy container IDs
func (hc *HealthChecker) GetAllHealthyContainers() []string {
	hc.mu.Lock()
	defer hc.mu.Unlock()

	var healthy []string
	for id, status := range hc.healthStatus {
		if status.IsHealthy {
			healthy = append(healthy, id)
		}
	}
	return healthy
}

// GetHealthSummary returns a summary of all health checks
func (hc *HealthChecker) GetHealthSummary() map[string]interface{} {
	hc.mu.Lock()
	defer hc.mu.Unlock()

	summary := map[string]interface{}{
		"total_targets":     len(hc.healthStatus),
		"healthy_targets":   0,
		"unhealthy_targets": 0,
		"targets":           map[string]interface{}{},
	}

	for id, s := range hc.healthStatus {
		target := map[string]interface{}{
			"healthy":              s.IsHealthy,
			"consecutive_failures": s.ConsecutiveFailures,
			"consecutive_success":  s.ConsecutiveSuccess,
			"last_success":         s.LastSuccess,
			"response_time_ms":     s.ResponseTimeMS,
		}
		if s.IsHealthy {
			summary["healthy_targets"] = summary["healthy_targets"].(int) + 1
		} else {
			summary["unhealthy_targets"] = summary["unhealthy_targets"].(int) + 1
		}
		summary["targets"].(map[string]interface{})[id] = target
	}
	return summary
}
