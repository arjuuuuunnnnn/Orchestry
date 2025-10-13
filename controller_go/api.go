package controller

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/client"
	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

// API Request/Response Models

// AppSpec represents the application specification
type AppSpec struct {
	APIVersion  string                 `json:"apiVersion"`
	Kind        string                 `json:"kind"`
	Metadata    map[string]interface{} `json:"metadata"`
	Spec        map[string]interface{} `json:"spec"`
	Scaling     map[string]interface{} `json:"scaling,omitempty"`
	HealthCheck map[string]interface{} `json:"healthCheck,omitempty"`
}

// ScaleRequest represents a manual scaling request
type ScaleRequest struct {
	Replicas int `json:"replicas" binding:"required,min=0,max=100"`
}

// PolicyRequest represents a scaling policy update request
type PolicyRequest struct {
	Policy map[string]interface{} `json:"policy" binding:"required"`
}

// SimulatedMetricsRequest represents simulated metrics for testing
type SimulatedMetricsRequest struct {
	RPS               float64 `json:"rps"`
	P95LatencyMs      float64 `json:"p95LatencyMs"`
	ActiveConnections int     `json:"activeConnections"`
	CPUPercent        float64 `json:"cpuPercent"`
	MemoryPercent     float64 `json:"memoryPercent"`
	HealthyReplicas   *int    `json:"healthyReplicas"`
	Evaluate          bool    `json:"evaluate"`
}

// AppRegistrationResponse represents the response after registering an app
type AppRegistrationResponse struct {
	Status  string `json:"status"`
	App     string `json:"app"`
	Message string `json:"message,omitempty"`
}

// AppStatusResponse represents the app status response
type AppStatusResponse struct {
	App           string                   `json:"app"`
	Status        string                   `json:"status"`
	Replicas      int                      `json:"replicas"`
	ReadyReplicas int                      `json:"ready_replicas"`
	Instances     []map[string]interface{} `json:"instances"`
	Mode          string                   `json:"mode"`
}

// APIServer represents the FastAPI equivalent server
type APIServer struct {
	appManager        *AppManager
	stateStore        *PostgresStateStore
	nginxManager      *NginxManagerImpl
	autoScaler        *AutoScaler
	healthChecker     *HealthChecker
	clusterController *DistributedController
	router            *gin.Engine
	dockerClient      *client.Client
}

// NewAPIServer creates a new API server instance
func NewAPIServer(
	appManager *AppManager,
	stateStore *PostgresStateStore,
	nginxManager *NginxManagerImpl,
	autoScaler *AutoScaler,
	healthChecker *HealthChecker,
	clusterController *DistributedController,
) (*APIServer, error) {
	// Create Docker client
	dockerClient, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, fmt.Errorf("failed to create Docker client: %w", err)
	}

	// Set Gin to release mode for production
	gin.SetMode(gin.ReleaseMode)

	router := gin.Default()

	// Add CORS middleware
	router.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Content-Type", "Accept", "Authorization"},
		ExposeHeaders:    []string{"Content-Length", "X-Current-Leader"},
		AllowCredentials: true,
	}))

	server := &APIServer{
		appManager:        appManager,
		stateStore:        stateStore,
		nginxManager:      nginxManager,
		autoScaler:        autoScaler,
		healthChecker:     healthChecker,
		clusterController: clusterController,
		router:            router,
		dockerClient:      dockerClient,
	}

	server.setupRoutes()

	return server, nil
}

// setupRoutes sets up all API routes
func (s *APIServer) setupRoutes() {
	// App management endpoints
	s.router.POST("/apps/register", s.leaderRequired(s.registerApp))
	s.router.POST("/apps/:name/up", s.leaderRequired(s.startApp))
	s.router.POST("/apps/:name/down", s.leaderRequired(s.stopApp))
	s.router.GET("/apps/:name/status", s.appStatus)
	s.router.POST("/apps/:name/scale", s.leaderRequired(s.scaleApp))
	s.router.POST("/apps/:name/policy", s.leaderRequired(s.setScalingPolicy))
	s.router.GET("/apps", s.listApps)
	s.router.GET("/apps/:name/raw", s.getAppRawSpec)
	s.router.GET("/apps/:name/logs", s.getAppLogs)
	s.router.GET("/apps/:name/metrics", s.getAppMetrics)
	s.router.POST("/apps/:name/simulateMetrics", s.leaderRequired(s.simulateMetrics))

	// System metrics and events
	s.router.GET("/metrics", s.getSystemMetrics)
	s.router.GET("/events", s.getEvents)

	// Cluster endpoints
	s.router.GET("/cluster/status", s.getClusterStatus)
	s.router.GET("/cluster/leader", s.getClusterLeader)
	s.router.GET("/cluster/health", s.clusterHealthCheck)

	// Health check
	s.router.GET("/health", s.healthCheck)
}

// Middleware: leaderRequired ensures only the leader can execute certain operations
func (s *APIServer) leaderRequired(handler gin.HandlerFunc) gin.HandlerFunc {
	return func(c *gin.Context) {
		if s.clusterController != nil && !s.clusterController.isLeader {
			leaderInfo := s.clusterController.GetLeaderInfo()
			if leaderInfo != nil {
				c.Header("X-Current-Leader", leaderInfo["leader_id"].(string))
				c.JSON(http.StatusServiceUnavailable, gin.H{
					"error":  fmt.Sprintf("Not the leader. Leader is: %s", leaderInfo["leader_id"]),
					"leader": leaderInfo["leader_id"],
				})
				return
			}
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"error": "No leader elected, cluster not ready",
			})
			return
		}
		handler(c)
	}
}

// Handler: registerApp registers a new application
func (s *APIServer) registerApp(c *gin.Context) {
	var appSpec AppSpec
	if err := c.ShouldBindJSON(&appSpec); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Convert AppSpec to map for manager
	specMap := map[string]interface{}{
		"apiVersion":  appSpec.APIVersion,
		"kind":        appSpec.Kind,
		"metadata":    appSpec.Metadata,
		"spec":        appSpec.Spec,
		"scaling":     appSpec.Scaling,
		"healthCheck": appSpec.HealthCheck,
	}

	// Register the app
	result := s.appManager.Register(specMap)

	if errMsg, ok := result["error"]; ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": errMsg})
		return
	}

	// Get app name from metadata
	metadata, ok := appSpec.Metadata["name"]
	if !ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": "App name is required in metadata"})
		return
	}
	appName := metadata.(string)

	// Set up default scaling policy from the scaling section
	scalingConfig := appSpec.Scaling
	if scalingConfig == nil {
		scalingConfig = make(map[string]interface{})
	}

	policy := ScalingPolicy{
		MinReplicas:          getIntFromMap(scalingConfig, "minReplicas", 1),
		MaxReplicas:          getIntFromMap(scalingConfig, "maxReplicas", 5),
		TargetRPSPerReplica:  getIntFromMap(scalingConfig, "targetRPSPerReplica", 50),
		MaxP95LatencyMs:      getIntFromMap(scalingConfig, "maxP95LatencyMs", 250),
		ScaleOutThresholdPct: getIntFromMap(scalingConfig, "scaleOutThresholdPct", 80),
		ScaleInThresholdPct:  getIntFromMap(scalingConfig, "scaleInThresholdPct", 30),
		WindowSeconds:        getIntFromMap(scalingConfig, "windowSeconds", 60),
		CooldownSeconds:      getIntFromMap(scalingConfig, "cooldownSeconds", 300),
	}

	if err := s.autoScaler.SetPolicy(appName, policy); err != nil {
		log.Printf("Failed to set scaling policy: %v", err)
	}

	// Log event
	if err := s.stateStore.LogEvent(appName, "registered", map[string]interface{}{
		"spec": appSpec.Spec,
	}); err != nil {
		log.Printf("Failed to log event: %v", err)
	}

	c.JSON(http.StatusOK, AppRegistrationResponse{
		Status:  "registered",
		App:     appName,
		Message: "Application registered successfully",
	})
}

// Handler: startApp starts an application
func (s *APIServer) startApp(c *gin.Context) {
	name := c.Param("name")

	result := s.appManager.Start(name)

	if errMsg, ok := result["error"]; ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": errMsg})
		return
	}

	// Log event
	if err := s.stateStore.LogEvent(name, "started", result); err != nil {
		log.Printf("Failed to log event: %v", err)
	}

	c.JSON(http.StatusOK, result)
}

// Handler: stopApp stops an application
func (s *APIServer) stopApp(c *gin.Context) {
	name := c.Param("name")

	result := s.appManager.Stop(name)

	if errMsg, ok := result["error"]; ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": errMsg})
		return
	}

	// Log event
	if err := s.stateStore.LogEvent(name, "stopped", result); err != nil {
		log.Printf("Failed to log event: %v", err)
	}

	c.JSON(http.StatusOK, result)
}

// Handler: appStatus gets the status of an application
func (s *APIServer) appStatus(c *gin.Context) {
	name := c.Param("name")

	result := s.appManager.Status(name)

	if errMsg, ok := result["error"]; ok {
		c.JSON(http.StatusNotFound, gin.H{"error": errMsg})
		return
	}

	// Get app mode from database
	appRecord, err := s.stateStore.GetApp(name)
	appMode := "auto"
	if err == nil && appRecord != nil {
		appMode = appRecord.Mode
	}

	// Add mode to the result
	result["mode"] = appMode

	// Convert to AppStatusResponse
	instances := []map[string]interface{}{}
	if instancesRaw, ok := result["instances"]; ok {
		if instList, ok := instancesRaw.([]map[string]interface{}); ok {
			instances = instList
		}
	}

	response := AppStatusResponse{
		App:           name,
		Status:        result["status"].(string),
		Replicas:      result["replicas"].(int),
		ReadyReplicas: result["ready_replicas"].(int),
		Instances:     instances,
		Mode:          appMode,
	}

	c.JSON(http.StatusOK, response)
}

// Handler: scaleApp manually scales an application
func (s *APIServer) scaleApp(c *gin.Context) {
	name := c.Param("name")

	var scaleReq ScaleRequest
	if err := c.ShouldBindJSON(&scaleReq); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Get current replicas
	currentReplicas := 0
	if instances, ok := s.appManager.instances[name]; ok {
		currentReplicas = len(instances)
	}

	result := s.appManager.Scale(name, scaleReq.Replicas)

	if errMsg, ok := result["error"]; ok {
		c.JSON(http.StatusBadRequest, gin.H{"error": errMsg})
		return
	}

	// Log scaling action
	if err := s.stateStore.LogScalingAction(
		name,
		currentReplicas,
		scaleReq.Replicas,
		"Manual scaling",
		[]string{"manual"},
		nil,
	); err != nil {
		log.Printf("Failed to log scaling action: %v", err)
	}

	// Log event
	if err := s.stateStore.LogEvent(name, "manual_scale", map[string]interface{}{
		"old_replicas": currentReplicas,
		"new_replicas": scaleReq.Replicas,
	}); err != nil {
		log.Printf("Failed to log event: %v", err)
	}

	c.JSON(http.StatusOK, result)
}

// Handler: setScalingPolicy updates scaling policy for an application
func (s *APIServer) setScalingPolicy(c *gin.Context) {
	name := c.Param("name")

	var policyReq PolicyRequest
	if err := c.ShouldBindJSON(&policyReq); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	policyData := policyReq.Policy

	policy := ScalingPolicy{
		MinReplicas:          getIntFromMap(policyData, "minReplicas", 1),
		MaxReplicas:          getIntFromMap(policyData, "maxReplicas", 5),
		TargetRPSPerReplica:  getIntFromMap(policyData, "targetRPSPerReplica", 50),
		MaxP95LatencyMs:      getIntFromMap(policyData, "maxP95LatencyMs", 250),
		ScaleOutThresholdPct: getIntFromMap(policyData, "scaleOutThresholdPct", 80),
		ScaleInThresholdPct:  getIntFromMap(policyData, "scaleInThresholdPct", 30),
		WindowSeconds:        getIntFromMap(policyData, "windowSeconds", 20),
		CooldownSeconds:      getIntFromMap(policyData, "cooldownSeconds", 30),
	}

	if err := s.autoScaler.SetPolicy(name, policy); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Log event
	if err := s.stateStore.LogEvent(name, "policy_updated", policyData); err != nil {
		log.Printf("Failed to log event: %v", err)
	}

	c.JSON(http.StatusOK, gin.H{
		"status": "updated",
		"app":    name,
		"policy": policyData,
	})
}

// Handler: listApps lists all registered applications
func (s *APIServer) listApps(c *gin.Context) {
	apps, err := s.stateStore.ListApps()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	// Add runtime status
	appList := make([]map[string]interface{}, 0, len(apps))
	for _, app := range apps {
		appMap := map[string]interface{}{
			"name":       app.Name,
			"status":     app.Status,
			"replicas":   app.Replicas,
			"created_at": app.CreatedAt,
			"updated_at": app.UpdatedAt,
			"mode":       app.Mode,
		}

		// Get runtime status
		statusResult := s.appManager.Status(app.Name)
		if _, ok := statusResult["error"]; !ok {
			appMap["status"] = statusResult["status"]
			appMap["replicas"] = statusResult["replicas"]
			appMap["ready_replicas"] = statusResult["ready_replicas"]
		} else {
			appMap["status"] = "unknown"
			appMap["replicas"] = 0
			appMap["ready_replicas"] = 0
		}

		appList = append(appList, appMap)
	}

	c.JSON(http.StatusOK, gin.H{"apps": appList})
}

// Handler: getAppRawSpec gets the raw and parsed spec for an application
func (s *APIServer) getAppRawSpec(c *gin.Context) {
	name := c.Param("name")

	// Get the parsed spec (normalized)
	parsedSpec, err := s.stateStore.GetApp(name)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": fmt.Sprintf("App %s not found", name)})
		return
	}

	// Get the raw spec (as submitted by user)
	rawSpec, err := s.stateStore.GetRawSpec(name)
	if err != nil {
		log.Printf("Failed to get raw spec: %v", err)
	}

	c.JSON(http.StatusOK, gin.H{
		"name":   name,
		"raw":    rawSpec,
		"parsed": parsedSpec,
	})
}

// Handler: getAppLogs gets logs for an application
func (s *APIServer) getAppLogs(c *gin.Context) {
	name := c.Param("name")
	linesStr := c.DefaultQuery("lines", "100")
	lines, err := strconv.Atoi(linesStr)
	if err != nil {
		lines = 100
	}

	instances, exists := s.appManager.instances[name]
	if !exists {
		c.JSON(http.StatusNotFound, gin.H{"error": "App not found or not running"})
		return
	}

	if len(instances) == 0 {
		c.JSON(http.StatusOK, gin.H{
			"app":  name,
			"logs": []interface{}{},
		})
		return
	}

	allLogs := []map[string]interface{}{}

	// Collect logs from all container instances
	for _, instance := range instances {
		containerLogs, err := s.dockerClient.ContainerLogs(
			context.Background(),
			instance.ContainerID,
			types.ContainerLogsOptions{
				ShowStdout: true,
				ShowStderr: true,
				Tail:       strconv.Itoa(lines),
				Timestamps: true,
			},
		)
		if err != nil {
			log.Printf("Failed to get logs from container %s: %v", instance.ContainerID[:12], err)
			continue
		}
		defer containerLogs.Close()

		// Parse logs
		// Docker log format: "2023-01-01T12:00:00.000000000Z message"
		buf := make([]byte, 8192)
		for {
			n, err := containerLogs.Read(buf)
			if err != nil {
				break
			}
			if n > 0 {
				logLine := string(buf[:n])
				// Parse timestamp and message (simplified)
				parts := parseDockerLog(logLine)
				for _, part := range parts {
					if part != "" {
						allLogs = append(allLogs, map[string]interface{}{
							"timestamp":      time.Now().Unix(),
							"container":      instance.ContainerID[:12],
							"container_full": instance.ContainerID,
							"message":        part,
						})
					}
				}
			}
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"app":              name,
		"total_containers": len(instances),
		"logs":             allLogs,
	})
}

// Handler: getAppMetrics gets metrics for an application
func (s *APIServer) getAppMetrics(c *gin.Context) {
	name := c.Param("name")

	metricsSummary := s.autoScaler.GetMetricsSummary(name)
	scalingHistory, err := s.stateStore.GetScalingHistory(name, 10)
	if err != nil {
		log.Printf("Failed to get scaling history: %v", err)
		scalingHistory = []interface{}{}
	}

	c.JSON(http.StatusOK, gin.H{
		"app":             name,
		"metrics":         metricsSummary,
		"scaling_history": scalingHistory,
	})
}

// Handler: simulateMetrics injects simulated metrics for an app
func (s *APIServer) simulateMetrics(c *gin.Context) {
	name := c.Param("name")

	var sim SimulatedMetricsRequest
	if err := c.ShouldBindJSON(&sim); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	instances, exists := s.appManager.instances[name]
	if !exists {
		c.JSON(http.StatusNotFound, gin.H{"error": "App not running"})
		return
	}

	replicaCount := len(instances)
	healthy := 0
	for _, inst := range instances {
		if inst.State == "ready" {
			healthy++
		}
	}

	healthyReplicas := healthy
	if sim.HealthyReplicas != nil {
		healthyReplicas = *sim.HealthyReplicas
	}

	metrics := ScalingMetrics{
		RPS:               sim.RPS,
		P95LatencyMs:      sim.P95LatencyMs,
		ActiveConnections: sim.ActiveConnections,
		CPUPercent:        sim.CPUPercent,
		MemoryPercent:     sim.MemoryPercent,
		HealthyReplicas:   healthyReplicas,
		TotalReplicas:     replicaCount,
	}

	s.autoScaler.AddMetrics(name, metrics)

	var evaluation *ScalingDecision
	var action map[string]interface{}

	if sim.Evaluate {
		// Get app mode from database
		appRecord, _ := s.stateStore.GetApp(name)
		appMode := "auto"
		if appRecord != nil {
			appMode = appRecord.Mode
		}

		eval := s.autoScaler.EvaluateScaling(name, replicaCount, appMode)
		evaluation = &eval

		if evaluation.ShouldScale {
			result := s.appManager.Scale(name, evaluation.TargetReplicas)
			if result["status"] == "scaled" {
				s.autoScaler.RecordScalingAction(name, evaluation.TargetReplicas)
				s.stateStore.LogScalingAction(
					name,
					evaluation.CurrentReplicas,
					evaluation.TargetReplicas,
					evaluation.Reason,
					evaluation.TriggeredBy,
					&evaluation.Metrics,
				)
				action = map[string]interface{}{
					"scaled": true,
					"from":   evaluation.CurrentReplicas,
					"to":     evaluation.TargetReplicas,
					"reason": evaluation.Reason,
				}
			} else {
				action = map[string]interface{}{
					"scaled": false,
					"error":  result,
				}
			}
		}
	}

	response := gin.H{
		"app":           name,
		"metrics_added": metricsToMap(metrics),
	}

	if evaluation != nil {
		response["evaluation"] = gin.H{
			"should_scale":    evaluation.ShouldScale,
			"target_replicas": evaluation.TargetReplicas,
			"reason":          evaluation.Reason,
			"scale_factors":   s.autoScaler.GetLastScaleFactors(name),
		}
	}

	if action != nil {
		response["action"] = action
	}

	c.JSON(http.StatusOK, response)
}

// Handler: getSystemMetrics gets system-wide metrics for monitoring
func (s *APIServer) getSystemMetrics(c *gin.Context) {
	allApps, err := s.stateStore.ListApps()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	totalApps := len(allApps)
	runningApps := 0
	totalInstances := 0
	healthyInstances := 0

	for _, app := range allApps {
		if instances, ok := s.appManager.instances[app.Name]; ok && len(instances) > 0 {
			runningApps++
			totalInstances += len(instances)
			for _, inst := range instances {
				if inst.State == "ready" {
					healthyInstances++
				}
			}
		}
	}

	// Get nginx status
	nginxStatus, err := s.nginxManager.GetNginxStatus()
	if err != nil {
		log.Printf("Failed to get nginx status: %v", err)
		nginxStatus = map[string]interface{}{"error": err.Error()}
	}

	// Get health check summary
	healthSummary := s.healthChecker.GetHealthSummary()

	// Get cluster status if available
	var clusterStatus interface{}
	if s.clusterController != nil {
		clusterStatus = s.clusterController.GetClusterStatus()
	}

	c.JSON(http.StatusOK, gin.H{
		"timestamp": time.Now().Unix(),
		"cluster":   clusterStatus,
		"apps": gin.H{
			"total":   totalApps,
			"running": runningApps,
		},
		"instances": gin.H{
			"total":     totalInstances,
			"healthy":   healthyInstances,
			"unhealthy": totalInstances - healthyInstances,
		},
		"nginx":         nginxStatus,
		"health_checks": healthSummary,
	})
}

// Handler: getEvents gets recent events
func (s *APIServer) getEvents(c *gin.Context) {
	app := c.Query("app")
	limitStr := c.DefaultQuery("limit", "100")
	limit, err := strconv.Atoi(limitStr)
	if err != nil {
		limit = 100
	}

	events, err := s.stateStore.GetEvents(app, limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"events": events})
}

// Handler: getClusterStatus gets detailed cluster status and membership
func (s *APIServer) getClusterStatus(c *gin.Context) {
	if s.clusterController == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Clustering not enabled"})
		return
	}

	status := s.clusterController.GetClusterStatus()
	c.JSON(http.StatusOK, status)
}

// Handler: getClusterLeader gets current cluster leader information
func (s *APIServer) getClusterLeader(c *gin.Context) {
	if s.clusterController == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "Clustering not enabled"})
		return
	}

	leaderInfo := s.clusterController.GetLeaderInfo()
	if leaderInfo != nil {
		c.JSON(http.StatusOK, leaderInfo)
	} else {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "No leader elected"})
	}
}

// Handler: clusterHealthCheck cluster-aware health check that includes leadership status
func (s *APIServer) clusterHealthCheck(c *gin.Context) {
	if s.clusterController == nil {
		c.JSON(http.StatusOK, gin.H{
			"status":     "healthy",
			"clustering": "disabled",
			"timestamp":  time.Now().Unix(),
			"version":    "1.0.0",
		})
		return
	}

	clusterStatus := s.clusterController.GetClusterStatus()
	isReady := s.clusterController.IsClusterReady()

	status := "healthy"
	if !isReady {
		status = "degraded"
	}

	c.JSON(http.StatusOK, gin.H{
		"status":        status,
		"clustering":    "enabled",
		"node_id":       clusterStatus["node_id"],
		"state":         clusterStatus["state"],
		"is_leader":     clusterStatus["is_leader"],
		"leader_id":     clusterStatus["leader_id"],
		"cluster_size":  clusterStatus["cluster_size"],
		"cluster_ready": isReady,
		"timestamp":     time.Now().Unix(),
		"version":       "1.0.0",
	})
}

// Handler: healthCheck health check endpoint
func (s *APIServer) healthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":    "healthy",
		"timestamp": time.Now().Unix(),
		"version":   "1.0.0",
	})
}

// Run starts the API server
func (s *APIServer) Run(addr string) error {
	log.Printf("Starting Orchestry Controller API on %s", addr)
	return s.router.Run(addr)
}

// Utility functions

// getIntFromMap safely extracts an int from a map with a default value
func getIntFromMap(m map[string]interface{}, key string, defaultVal int) int {
	if val, ok := m[key]; ok {
		switch v := val.(type) {
		case int:
			return v
		case float64:
			return int(v)
		case string:
			if i, err := strconv.Atoi(v); err == nil {
				return i
			}
		}
	}
	return defaultVal
}

// parseDockerLog parses Docker log output
func parseDockerLog(logLine string) []string {
	// Simple implementation - in production you'd want more robust parsing
	lines := []string{}
	for _, line := range splitLines(logLine) {
		if len(line) > 8 {
			// Skip Docker's 8-byte header
			lines = append(lines, line[8:])
		}
	}
	return lines
}

func splitLines(s string) []string {
	result := []string{}
	current := ""
	for _, char := range s {
		if char == '\n' {
			if current != "" {
				result = append(result, current)
				current = ""
			}
		} else {
			current += string(char)
		}
	}
	if current != "" {
		result = append(result, current)
	}
	return result
}

// metricsToMap converts ScalingMetrics to a map
func metricsToMap(m ScalingMetrics) map[string]interface{} {
	return map[string]interface{}{
		"rps":                m.RPS,
		"p95_latency_ms":     m.P95LatencyMs,
		"active_connections": m.ActiveConnections,
		"cpu_percent":        m.CPUPercent,
		"memory_percent":     m.MemoryPercent,
		"healthy_replicas":   m.HealthyReplicas,
		"total_replicas":     m.TotalReplicas,
	}
}
