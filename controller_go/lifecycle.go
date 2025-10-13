package controller

import (
	"context"
	"log"
	"os"
	"strconv"
	"sync"
	"time"

	"statego"
)

// Lifecycle manages the startup and shutdown of all controller components
type Lifecycle struct {
	// Components
	appManager        *AppManager
	stateStore        *PostgresStateStore
	nginxManager      *NginxManagerImpl
	autoScaler        *AutoScaler
	healthChecker     *HealthChecker
	clusterController *DistributedController
	apiServer         *APIServer

	// Monitoring state
	monitoringActive bool
	monitoringCancel context.CancelFunc
	monitoringCtx    context.Context
	monitoringWg     sync.WaitGroup

	// Nginx tracking for RPS calculation
	prevNginxRequests  *int
	prevNginxTime      *float64
	nginxTrackingMutex sync.Mutex
}

// NewLifecycle creates a new lifecycle manager
func NewLifecycle() *Lifecycle {
	return &Lifecycle{}
}

// Startup initializes all components
func (l *Lifecycle) Startup() error {
	log.Println("🚀 Starting Orchestry Controller...")

	// 1. Initialize PostgreSQL HA database cluster
	log.Println("🚀 Initializing PostgreSQL HA database cluster...")

	// Get database configuration from environment
	primaryHost := os.Getenv("POSTGRES_PRIMARY_HOST")
	if primaryHost == "" {
		primaryHost = "postgres-primary"
	}

	primaryPort := 5432
	if portStr := os.Getenv("POSTGRES_PRIMARY_PORT"); portStr != "" {
		if p, err := strconv.Atoi(portStr); err == nil {
			primaryPort = p
		}
	}

	replicaHost := os.Getenv("POSTGRES_REPLICA_HOST")
	if replicaHost == "" {
		replicaHost = "postgres-replica"
	}

	replicaPort := 5432
	if portStr := os.Getenv("POSTGRES_REPLICA_PORT"); portStr != "" {
		if p, err := strconv.Atoi(portStr); err == nil {
			replicaPort = p
		}
	}

	database := os.Getenv("POSTGRES_DB")
	if database == "" {
		database = "orchestry"
	}

	username := os.Getenv("POSTGRES_USER")
	if username == "" {
		username = "orchestry"
	}

	password := os.Getenv("POSTGRES_PASSWORD")
	if password == "" {
		password = "orchestry_password"
	}

	minConn := 5
	if connStr := os.Getenv("POSTGRES_MIN_CONNECTIONS"); connStr != "" {
		if c, err := strconv.Atoi(connStr); err == nil {
			minConn = c
		}
	}

	maxConn := 20
	if connStr := os.Getenv("POSTGRES_MAX_CONNECTIONS"); connStr != "" {
		if c, err := strconv.Atoi(connStr); err == nil {
			maxConn = c
		}
	}

	dbManager, err := statego.NewDatabaseManager(
		primaryHost, primaryPort,
		replicaHost, replicaPort,
		database, username, password,
		minConn, maxConn,
	)
	if err != nil {
		return err
	}
	l.stateStore = NewPostgresStateStore(dbManager)

	// 2. Initialize distributed controller cluster with leader election
	log.Println("🏗️  Initializing distributed controller cluster...")
	nodeID := os.Getenv("CLUSTER_NODE_ID")
	hostname := os.Getenv("CLUSTER_HOSTNAME")
	if hostname == "" {
		hostname = "localhost"
	}

	portStr := os.Getenv("ORCHESTRY_PORT")
	if portStr == "" {
		portStr = "8000"
	}
	port, err := strconv.Atoi(portStr)
	if err != nil {
		return err
	}

	// Cluster configuration parameters
	leaseTTL := 10         // seconds
	heartbeatInterval := 3 // seconds
	electionTimeout := 5   // seconds

	l.clusterController, err = NewDistributedController(
		nodeID, hostname, port, dbManager,
		leaseTTL, heartbeatInterval, electionTimeout,
	)
	if err != nil {
		return err
	}

	// Set up cluster event handlers
	l.clusterController.onBecomeLeader = l.onBecomeLeader
	l.clusterController.onLoseLeadership = l.onLoseLeadership
	l.clusterController.onClusterChange = l.onClusterChange

	// Start the cluster
	if err := l.clusterController.Start(); err != nil {
		return err
	}

	// 3. Initialize other components
	nginxContainer := os.Getenv("ORCHESTRY_NGINX_CONTAINER")
	nginxConfDir := os.Getenv("ORCHESTRY_NGINX_CONF_DIR")
	l.nginxManager, err = NewNginxManager(nginxContainer, nginxConfDir, "")
	if err != nil {
		return err
	}

	l.autoScaler = NewAutoScaler()
	l.healthChecker = NewHealthChecker()

	l.appManager, err = NewAppManager(l.stateStore, l.nginxManager)
	if err != nil {
		return err
	}

	// Set health checker in app manager
	l.appManager.healthChecker = l.healthChecker

	// 4. Start health checker
	l.healthChecker.Start()

	// 5. Reconcile existing containers BEFORE cleanup
	log.Println("🔄 Reconciling existing containers...")
	adoptedSummary := l.appManager.ReconcileApp("")
	log.Printf("Reconciliation summary on startup: adopted %d containers", adoptedSummary)

	// 6. Restore scaling policies from database
	log.Println("📋 Restoring scaling policies from database...")
	if err := l.restoreScalingPolicies(); err != nil {
		log.Printf("Warning: Failed to restore some scaling policies: %v", err)
	}

	// 7. Create API server
	l.apiServer, err = NewAPIServer(
		l.appManager,
		l.stateStore,
		l.nginxManager,
		l.autoScaler,
		l.healthChecker,
		l.clusterController,
	)
	if err != nil {
		return err
	}

	// 8. Start background monitoring
	l.monitoringCtx, l.monitoringCancel = context.WithCancel(context.Background())
	l.monitoringActive = true
	l.monitoringWg.Add(1)
	go l.backgroundMonitoring()

	log.Println("✅ Orchestry Controller started successfully")
	return nil
}

// Shutdown cleans up all resources
func (l *Lifecycle) Shutdown() {
	log.Println("🛑 Shutting down Orchestry Controller...")

	// Stop monitoring
	l.monitoringActive = false
	if l.monitoringCancel != nil {
		l.monitoringCancel()
	}
	l.monitoringWg.Wait()

	// Stop cluster
	if l.clusterController != nil {
		l.clusterController.Stop()
	}

	// Stop container monitoring
	if l.appManager != nil {
		l.appManager.StopContainerMonitoring()
	}

	// Stop health checker
	if l.healthChecker != nil {
		l.healthChecker.Stop()
	}

	// Close database connections
	if l.stateStore != nil && l.stateStore.dbManager != nil {
		// Implement close if needed
	}

	log.Println("✅ Orchestry Controller shut down")
}

// Run starts the API server (blocking call)
func (l *Lifecycle) Run() error {
	host := os.Getenv("ORCHESTRY_HOST")
	if host == "" {
		host = "0.0.0.0"
	}

	portStr := os.Getenv("ORCHESTRY_PORT")
	if portStr == "" {
		portStr = "8000"
	}

	addr := host + ":" + portStr
	return l.apiServer.Run(addr)
}

// onBecomeLeader is called when this node becomes the cluster leader
func (l *Lifecycle) onBecomeLeader() {
	log.Println("👑 This node has become the cluster leader - taking control of operations")

	// Reconcile existing containers
	if l.appManager != nil && l.autoScaler != nil {
		adoptedSummary := l.appManager.ReconcileApp("")
		log.Printf("✅ Leader reconciled existing containers: %d adopted", adoptedSummary)

		// Restore scaling policies
		if err := l.restoreScalingPolicies(); err != nil {
			log.Printf("❌ Leader failed to restore scaling policies: %v", err)
		}

		// Start container monitoring
		l.appManager.StartContainerMonitoring()

		// Cleanup orphaned containers
		// Note: CleanupOrphanedContainers method needs to be implemented in manager.go
		log.Println("✅ Leader completed setup")
	}
}

// onLoseLeadership is called when this node loses leadership
func (l *Lifecycle) onLoseLeadership() {
	log.Println("💔 This node has lost cluster leadership - stepping down from operations")

	if l.appManager != nil {
		l.appManager.StopContainerMonitoring()
	}
}

// onClusterChange is called when cluster membership changes
func (l *Lifecycle) onClusterChange(nodes map[string]*ClusterNode) {
	nodeCount := len(nodes)
	nodeIDs := make([]string, 0, nodeCount)
	for _, node := range nodes {
		nodeIDs = append(nodeIDs, node.NodeID)
	}
	log.Printf("🔄 Cluster membership changed: %d nodes - %v", nodeCount, nodeIDs)
}

// restoreScalingPolicies restores scaling policies from the database
func (l *Lifecycle) restoreScalingPolicies() error {
	apps, err := l.stateStore.ListApps()
	if err != nil {
		return err
	}

	log.Printf("🔄 Restoring scaling policies for %d apps from database", len(apps))

	for _, app := range apps {
		appName := app.Name

		// Get full app record to access the spec with scaling config
		appRecord, err := l.stateStore.GetApp(appName)
		if err != nil || appRecord == nil {
			log.Printf("Warning: Could not get app record for %s", appName)
			continue
		}

		// Extract scaling config from spec
		scalingConfig, ok := appRecord.Spec["scaling"].(map[string]interface{})
		if !ok || scalingConfig == nil {
			log.Printf("No scaling config found for %s", appName)
			continue
		}

		// Create scaling policy
		policy := ScalingPolicy{
			MinReplicas:          getIntFromMapDefault(scalingConfig, "minReplicas", 1),
			MaxReplicas:          getIntFromMapDefault(scalingConfig, "maxReplicas", 5),
			TargetRPSPerReplica:  getIntFromMapDefault(scalingConfig, "targetRPSPerReplica", 50),
			MaxP95LatencyMs:      getIntFromMapDefault(scalingConfig, "maxP95LatencyMs", 250),
			ScaleOutThresholdPct: getIntFromMapDefault(scalingConfig, "scaleOutThresholdPct", 80),
			ScaleInThresholdPct:  getIntFromMapDefault(scalingConfig, "scaleInThresholdPct", 30),
			WindowSeconds:        getIntFromMapDefault(scalingConfig, "windowSeconds", 60),
			CooldownSeconds:      getIntFromMapDefault(scalingConfig, "cooldownSeconds", 300),
		}

		if err := l.autoScaler.SetPolicy(appName, policy); err != nil {
			log.Printf("❌ Failed to restore scaling policy for %s: %v", appName, err)
		} else {
			log.Printf("✅ Restored scaling policy for %s: targetRPS=%d, thresholds=%d%%/%d%%",
				appName, policy.TargetRPSPerReplica, policy.ScaleOutThresholdPct, policy.ScaleInThresholdPct)
		}
	}

	log.Println("✅ Completed scaling policy restoration from database")
	return nil
}

// backgroundMonitoring runs the monitoring and autoscaling loop
func (l *Lifecycle) backgroundMonitoring() {
	defer l.monitoringWg.Done()
	log.Println("Started background monitoring thread")

	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-l.monitoringCtx.Done():
			log.Println("Background monitoring thread stopped")
			return
		case <-ticker.C:
			if err := l.monitoringCycle(); err != nil {
				log.Printf("Error in background monitoring: %v", err)
			}
		}
	}
}

// monitoringCycle performs one monitoring and autoscaling cycle
func (l *Lifecycle) monitoringCycle() error {
	// Only run monitoring on the leader node
	if l.clusterController != nil && !l.clusterController.isLeader {
		return nil
	}

	// Get list of running apps only
	allApps, err := l.stateStore.ListApps()
	if err != nil {
		return err
	}

	// Filter to only running apps
	runningApps := []*AppRecord{}
	for _, app := range allApps {
		if app.Status == "running" {
			runningApps = append(runningApps, app)
		}
	}

	// Fetch nginx status for global metrics
	nginxStatus, err := l.nginxManager.GetNginxStatus()
	if err != nil {
		log.Printf("Warning: Unable to fetch nginx status: %v", err)
		nginxStatus = map[string]interface{}{}
	}

	// Compute global RPS from nginx
	rpsGlobal := l.computeGlobalRPS(nginxStatus)
	activeConnsGlobal := getIntFromMapDefault(nginxStatus, "active_connections", 0)

	// Calculate total replicas across all apps for fair-share metrics
	totalReplicasGlobal := 0
	for _, app := range runningApps {
		if instances, ok := l.appManager.instances[app.Name]; ok {
			totalReplicasGlobal += len(instances)
		}
	}

	// Process each running app
	for _, appInfo := range runningApps {
		appName := appInfo.Name

		// Get current instances
		instances, ok := l.appManager.instances[appName]
		if !ok || len(instances) == 0 {
			continue
		}

		// Update container stats
		l.appManager.UpdateContainerStats(appName)

		// Collect metrics
		healthyCount := 0
		totalCPU := 0.0
		totalMemory := 0.0

		for _, inst := range instances {
			if inst.State == "ready" {
				healthyCount++
			}
			totalCPU += inst.CPUPercent
			totalMemory += inst.MemoryPercent
		}

		avgCPU := totalCPU / float64(len(instances))
		avgMemory := totalMemory / float64(len(instances))

		// Fair-share distribution of global RPS & connections
		share := 0.0
		if totalReplicasGlobal > 0 {
			share = float64(len(instances)) / float64(totalReplicasGlobal)
		}
		appRPS := rpsGlobal * share
		appActiveConns := int(float64(activeConnsGlobal) * share)

		metrics := ScalingMetrics{
			RPS:               appRPS,
			P95LatencyMs:      0, // Not implemented yet
			ActiveConnections: appActiveConns,
			CPUPercent:        avgCPU,
			MemoryPercent:     avgMemory,
			HealthyReplicas:   healthyCount,
			TotalReplicas:     len(instances),
		}

		// Add metrics to scaler
		l.autoScaler.AddMetrics(appName, metrics)

		// Get app mode
		appRecord, _ := l.stateStore.GetApp(appName)
		appMode := "auto"
		if appRecord != nil {
			appMode = appRecord.Mode
		}

		// Evaluate scaling decision
		decision := l.autoScaler.Evaluate(appName, len(instances), appMode)

		// Log evaluation (useful for debugging)
		policy := l.autoScaler.GetPolicy(appName)
		if policy != nil {
			log.Printf("Scaling evaluation for %s: RPS=%.2f, Conns=%d, CPU=%.1f%%, Mem=%.1f%%, "+
				"Replicas=%d, Decision=%v, Reason=%s",
				appName, metrics.RPS, metrics.ActiveConnections, avgCPU, avgMemory,
				len(instances), decision.ShouldScale, decision.Reason)
		}

		// Execute scaling if needed
		if decision.ShouldScale {
			log.Printf("Scaling %s: %s", appName, decision.Reason)

			result := l.appManager.Scale(appName, decision.TargetReplicas)

			if result["status"] == "scaled" {
				// Record scaling action
				l.autoScaler.RecordScalingAction(appName, decision.TargetReplicas)

				// Log to state store
				l.stateStore.LogScalingAction(
					appName,
					decision.CurrentReplicas,
					decision.TargetReplicas,
					decision.Reason,
					decision.TriggeredBy,
					&decision.Metrics,
				)

				// Log event
				l.stateStore.LogEvent(appName, "scaled", map[string]interface{}{
					"old_replicas": decision.CurrentReplicas,
					"new_replicas": decision.TargetReplicas,
					"reason":       decision.Reason,
				})
			}
		}
	}

	return nil
}

// computeGlobalRPS computes RPS from nginx status
func (l *Lifecycle) computeGlobalRPS(nginxStatus map[string]interface{}) float64 {
	l.nginxTrackingMutex.Lock()
	defer l.nginxTrackingMutex.Unlock()

	currentRequests, ok := nginxStatus["requests"].(int)
	if !ok {
		return 0.0
	}

	now := float64(time.Now().Unix())

	if l.prevNginxRequests != nil && l.prevNginxTime != nil {
		deltaReq := currentRequests - *l.prevNginxRequests
		deltaTime := now - *l.prevNginxTime

		if deltaReq >= 0 && deltaTime > 0 {
			rps := float64(deltaReq) / deltaTime
			l.prevNginxRequests = &currentRequests
			l.prevNginxTime = &now
			return rps
		}
	}

	// Initialize tracking
	l.prevNginxRequests = &currentRequests
	l.prevNginxTime = &now
	return 0.0
}

// Helper function
func getIntFromMapDefault(m map[string]interface{}, key string, defaultVal int) int {
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

// UpdateContainerStats updates CPU and memory stats for containers
func (am *AppManager) UpdateContainerStats(appName string) {
	// This would fetch stats from Docker
	// Simplified for now - implement full stats gathering as needed
}
