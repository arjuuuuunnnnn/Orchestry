package controller

import (
	"context"
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
)

// ContainerInstance represents a running container instance
type ContainerInstance struct {
	ContainerID   string
	IP            string
	Port          int
	State         string // ready, draining, down
	CPUPercent    float64
	MemoryPercent float64
	LastSeen      time.Time
	Failures      int
}

// AppManager manages Docker containers and their lifecycle
type AppManager struct {
	client           *client.Client
	stateStore       StateStore
	nginx            NginxManager
	healthChecker    *HealthChecker
	instances        map[string][]*ContainerInstance
	lock             sync.RWMutex
	restartLock      sync.Mutex
	shutdown         bool
	monitoringActive bool
	monitoringCancel context.CancelFunc
	ctx              context.Context
}

// StateStore interface for app state persistence
type StateStore interface {
	GetApp(name string) (*AppRecord, error)
	SaveApp(record *AppRecord) error
	ListApps() ([]*AppRecord, error)
}

// AppRecord represents the stored application configuration
type AppRecord struct {
	Name      string
	Spec      map[string]interface{}
	Status    string
	CreatedAt time.Time
	UpdatedAt time.Time
	Replicas  int
	Mode      string
}

// NginxManager interface for nginx configuration
type NginxManager interface {
	UpdateUpstreams(appName string, servers []Server) error
	RemoveAppConfig(appName string) error
}

// Server represents an upstream server
type Server struct {
	IP   string
	Port int
}

// NewAppManager creates a new AppManager instance
func NewAppManager(stateStore StateStore, nginxManager NginxManager) (*AppManager, error) {
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, fmt.Errorf("failed to create docker client: %w", err)
	}

	ctx := context.Background()
	am := &AppManager{
		client:     cli,
		stateStore: stateStore,
		nginx:      nginxManager,
		instances:  make(map[string][]*ContainerInstance),
		ctx:        ctx,
	}

	if err := am.ensureNetwork(); err != nil {
		return nil, fmt.Errorf("failed to ensure network: %w", err)
	}

	return am, nil
}

// ensureNetwork ensures the orchestry network exists
func (am *AppManager) ensureNetwork() error {
	_, err := am.client.NetworkInspect(am.ctx, "orchestry", types.NetworkInspectOptions{})
	if err == nil {
		return nil
	}

	_, err = am.client.NetworkCreate(am.ctx, "orchestry", types.NetworkCreate{
		Driver: "bridge",
		Labels: map[string]string{
			"managed_by": "orchestry",
		},
	})
	return err
}

// Register registers a new application
func (am *AppManager) Register(spec map[string]interface{}) map[string]interface{} {
	metadata, ok := spec["metadata"].(map[string]interface{})
	if !ok {
		return map[string]interface{}{"error": "invalid metadata"}
	}

	appName, ok := metadata["name"].(string)
	if !ok {
		return map[string]interface{}{"error": "missing app name"}
	}

	appSpec, ok := spec["spec"].(map[string]interface{})
	if !ok {
		return map[string]interface{}{"error": "invalid spec"}
	}

	// Copy spec to avoid modifying original
	specCopy := make(map[string]interface{})
	for k, v := range appSpec {
		specCopy[k] = v
	}

	// Include scaling config
	if scaling, ok := spec["scaling"]; ok {
		specCopy["scaling"] = scaling
	}

	// Validate type
	if appType, ok := specCopy["type"].(string); !ok || appType != "http" {
		return map[string]interface{}{"error": "Only HTTP type is currently supported"}
	}

	// Validate ports
	ports, ok := specCopy["ports"]
	if !ok || ports == nil {
		return map[string]interface{}{"error": "HTTP apps must specify at least one port"}
	}

	// Handle healthCheck -> health mapping
	if healthCheck, ok := specCopy["healthCheck"]; ok {
		specCopy["health"] = healthCheck
		delete(specCopy, "healthCheck")
	}
	if healthCheck, ok := spec["healthCheck"]; ok {
		specCopy["health"] = healthCheck
	}

	// Merge labels
	if specCopy["labels"] == nil {
		specCopy["labels"] = make(map[string]interface{})
	}
	if metaLabels, ok := metadata["labels"].(map[string]interface{}); ok {
		labels := specCopy["labels"].(map[string]interface{})
		for k, v := range metaLabels {
			labels[k] = v
		}
	}

	// Extract scaling mode
	scalingMode := "auto"
	if scaling, ok := spec["scaling"].(map[string]interface{}); ok {
		if mode, ok := scaling["mode"].(string); ok {
			scalingMode = mode
		}
		specCopy["scaling"] = scaling
	}

	// Create app record with stopped status
	now := time.Now()
	appRecord := &AppRecord{
		Name:      appName,
		Spec:      specCopy,
		Status:    "stopped",
		CreatedAt: now,
		UpdatedAt: now,
		Replicas:  0,
		Mode:      scalingMode,
	}

	if err := am.stateStore.SaveApp(appRecord); err != nil {
		return map[string]interface{}{"error": err.Error()}
	}

	am.lock.Lock()
	am.instances[appName] = []*ContainerInstance{}
	am.lock.Unlock()

	log.Printf("Registered app %s with status='stopped'", appName)
	return map[string]interface{}{
		"status": "registered",
		"app":    appName,
	}
}

// Start starts the application containers
func (am *AppManager) Start(appName string) map[string]interface{} {
	log.Printf("Starting app %s", appName)

	appRecord, err := am.stateStore.GetApp(appName)
	if err != nil || appRecord == nil {
		return map[string]interface{}{"error": fmt.Sprintf("App %s not found", appName)}
	}

	// Set status to running
	appRecord.Status = "running"
	appRecord.UpdatedAt = time.Now()
	if err := am.stateStore.SaveApp(appRecord); err != nil {
		return map[string]interface{}{"error": err.Error()}
	}

	// Adopt existing containers
	adopted := am.ReconcileApp(appName)

	// Get scaling configuration
	scaling, _ := appRecord.Spec["scaling"].(map[string]interface{})
	minReplicas := 1
	if mr, ok := scaling["minReplicas"].(int); ok {
		minReplicas = mr
	} else if mr, ok := scaling["minReplicas"].(float64); ok {
		minReplicas = int(mr)
	}

	// Start additional replicas if needed
	am.lock.Lock()
	existingIndices := make(map[int]bool)
	for _, inst := range am.instances[appName] {
		c, err := am.client.ContainerInspect(am.ctx, inst.ContainerID)
		if err == nil {
			if idxStr := c.Config.Labels["orchestry.replica"]; idxStr != "" {
				if idx, err := strconv.Atoi(idxStr); err == nil {
					existingIndices[idx] = true
				}
			}
		}
	}

	nextIndex := 0
	started := 0
	for len(am.instances[appName]) < minReplicas {
		for existingIndices[nextIndex] {
			nextIndex++
		}
		if am.startContainer(appName, appRecord.Spec, nextIndex) != nil {
			existingIndices[nextIndex] = true
			started++
		}
		nextIndex++
	}
	total := len(am.instances[appName])
	am.lock.Unlock()

	am.updateNginxConfig(appName)

	log.Printf("App %s now running with %d replicas (adopted=%d, started=%d)", appName, total, adopted, started)
	return map[string]interface{}{
		"status":   "started",
		"app":      appName,
		"replicas": total,
		"adopted":  adopted,
		"started":  started,
	}
}

// startContainer starts a single container instance
func (am *AppManager) startContainer(appName string, appSpec map[string]interface{}, replicaIndex int) *ContainerInstance {
	ports, _ := appSpec["ports"].([]interface{})
	if len(ports) == 0 {
		return nil
	}
	portMap, _ := ports[0].(map[string]interface{})
	containerPort := 8080
	if cp, ok := portMap["containerPort"].(int); ok {
		containerPort = cp
	} else if cp, ok := portMap["containerPort"].(float64); ok {
		containerPort = int(cp)
	}

	image, _ := appSpec["image"].(string)
	appType, _ := appSpec["type"].(string)

	config := &container.Config{
		Image: image,
		Labels: map[string]string{
			"orchestry.app":     appName,
			"orchestry.replica": strconv.Itoa(replicaIndex),
			"orchestry.type":    appType,
		},
	}

	hostConfig := &container.HostConfig{
		RestartPolicy: container.RestartPolicy{Name: "unless-stopped"},
	}

	// Add resource limits
	if resources, ok := appSpec["resources"].(map[string]interface{}); ok {
		if cpuStr, ok := resources["cpu"].(string); ok {
			var cpuValue float64
			if strings.HasSuffix(cpuStr, "m") {
				if val, err := strconv.ParseFloat(cpuStr[:len(cpuStr)-1], 64); err == nil {
					cpuValue = val / 1000
				}
			} else if val, err := strconv.ParseFloat(cpuStr, 64); err == nil {
				cpuValue = val
			}
			hostConfig.NanoCPUs = int64(cpuValue * 1_000_000_000)
		}

		if memStr, ok := resources["memory"].(string); ok {
			var memBytes int64
			if strings.HasSuffix(memStr, "Mi") {
				if val, err := strconv.ParseInt(memStr[:len(memStr)-2], 10, 64); err == nil {
					memBytes = val * 1024 * 1024
				}
			} else if strings.HasSuffix(memStr, "Gi") {
				if val, err := strconv.ParseInt(memStr[:len(memStr)-2], 10, 64); err == nil {
					memBytes = val * 1024 * 1024 * 1024
				}
			}
			hostConfig.Memory = memBytes
		}
	}

	// Add environment variables
	if envList, ok := appSpec["env"].([]interface{}); ok {
		var envVars []string
		for _, envItem := range envList {
			envMap, _ := envItem.(map[string]interface{})
			name, _ := envMap["name"].(string)
			value, _ := envMap["value"].(string)
			envVars = append(envVars, fmt.Sprintf("%s=%s", name, value))
		}
		config.Env = envVars
	}

	networkingConfig := &network.NetworkingConfig{
		EndpointsConfig: map[string]*network.EndpointSettings{
			"orchestry": {},
		},
	}

	containerName := fmt.Sprintf("%s-%d", appName, replicaIndex)
	resp, err := am.client.ContainerCreate(am.ctx, config, hostConfig, networkingConfig, nil, containerName)
	if err != nil {
		log.Printf("Failed to create container %s: %v", containerName, err)
		return nil
	}

	if err := am.client.ContainerStart(am.ctx, resp.ID, types.ContainerStartOptions{}); err != nil {
		log.Printf("Failed to start container %s: %v", containerName, err)
		return nil
	}

	// Get container info
	containerJSON, err := am.client.ContainerInspect(am.ctx, resp.ID)
	if err != nil {
		log.Printf("Failed to inspect container %s: %v", containerName, err)
		return nil
	}

	containerIP := containerJSON.NetworkSettings.Networks["orchestry"].IPAddress

	instance := &ContainerInstance{
		ContainerID: resp.ID,
		IP:          containerIP,
		Port:        containerPort,
		State:       "ready",
		LastSeen:    time.Now(),
	}

	if am.instances[appName] == nil {
		am.instances[appName] = []*ContainerInstance{}
	}
	am.instances[appName] = append(am.instances[appName], instance)

	// Register with health checker if configured
	if health, ok := appSpec["health"].(map[string]interface{}); ok {
		healthConfig := createHealthConfig(health)
		if am.healthChecker != nil {
			am.healthChecker.AddTarget(resp.ID, containerIP, containerPort, healthConfig)
		}
	}

	log.Printf("Started container %s at %s:%d", containerName, containerIP, containerPort)
	return instance
}

// createHealthConfig creates a health config from spec
func createHealthConfig(health map[string]interface{}) HealthCheckConfig {
	config := HealthCheckConfig{
		Path:             "/health",
		IntervalSeconds:  10,
		TimeoutSeconds:   5,
		FailureThreshold: 3,
		SuccessThreshold: 2,
	}

	if path, ok := health["path"].(string); ok {
		config.Path = path
	}
	if interval, ok := health["interval"].(float64); ok {
		config.IntervalSeconds = int(interval)
	}
	if timeout, ok := health["timeout"].(float64); ok {
		config.TimeoutSeconds = int(timeout)
	}

	return config
}

// Stop stops all containers for an application
func (am *AppManager) Stop(appName string) map[string]interface{} {
	am.lock.Lock()
	defer am.lock.Unlock()

	instances, exists := am.instances[appName]
	if !exists {
		return map[string]interface{}{"error": fmt.Sprintf("App %s not found or not running", appName)}
	}

	// Update status
	appRecord, _ := am.stateStore.GetApp(appName)
	if appRecord != nil {
		appRecord.Status = "stopped"
		appRecord.UpdatedAt = time.Now()
		appRecord.Replicas = 0
		am.stateStore.SaveApp(appRecord)
	}

	stoppedCount := 0
	timeout := 30
	for _, instance := range instances {
		err := am.client.ContainerStop(am.ctx, instance.ContainerID, container.StopOptions{Timeout: &timeout})
		if err != nil {
			log.Printf("Failed to stop container %s: %v", instance.ContainerID, err)
			continue
		}

		if err := am.client.ContainerRemove(am.ctx, instance.ContainerID, types.ContainerRemoveOptions{}); err != nil {
			log.Printf("Failed to remove container %s: %v", instance.ContainerID, err)
		}

		if am.healthChecker != nil {
			am.healthChecker.RemoveTarget(instance.ContainerID)
		}

		stoppedCount++
	}

	delete(am.instances, appName)
	am.updateNginxConfig(appName)

	log.Printf("Stopped %d containers for app %s", stoppedCount, appName)
	return map[string]interface{}{
		"status":             "stopped",
		"app":                appName,
		"containers_stopped": stoppedCount,
	}
}

// ReconcileApp adopts existing containers for an app
func (am *AppManager) ReconcileApp(appName string) int {
	appRecord, err := am.stateStore.GetApp(appName)
	if err != nil || appRecord == nil {
		log.Printf("reconcile_app: app %s not found", appName)
		return 0
	}

	am.lock.Lock()
	defer am.lock.Unlock()

	if am.instances[appName] == nil {
		am.instances[appName] = []*ContainerInstance{}
	}

	filterArgs := filters.NewArgs()
	filterArgs.Add("label", fmt.Sprintf("orchestry.app=%s", appName))

	containers, err := am.client.ContainerList(am.ctx, types.ContainerListOptions{All: true, Filters: filterArgs})
	if err != nil {
		log.Printf("Failed to list containers: %v", err)
		return 0
	}

	adopted := 0
	for _, c := range containers {
		if c.State != "running" {
			log.Printf("Starting stopped container %s", c.Names[0])
			am.client.ContainerStart(am.ctx, c.ID, types.ContainerStartOptions{})
		}

		// Skip if already tracked
		alreadyTracked := false
		for _, inst := range am.instances[appName] {
			if inst.ContainerID == c.ID {
				alreadyTracked = true
				break
			}
		}
		if alreadyTracked {
			continue
		}

		containerJSON, err := am.client.ContainerInspect(am.ctx, c.ID)
		if err != nil {
			continue
		}

		ip := containerJSON.NetworkSettings.Networks["orchestry"].IPAddress
		ports, _ := appRecord.Spec["ports"].([]interface{})
		port := 8080
		if len(ports) > 0 {
			portMap, _ := ports[0].(map[string]interface{})
			if cp, ok := portMap["containerPort"].(int); ok {
				port = cp
			}
		}

		instance := &ContainerInstance{
			ContainerID: c.ID,
			IP:          ip,
			Port:        port,
			State:       "ready",
			LastSeen:    time.Now(),
		}
		am.instances[appName] = append(am.instances[appName], instance)

		// Register with health checker
		if health, ok := appRecord.Spec["health"].(map[string]interface{}); ok {
			healthConfig := createHealthConfig(health)
			if am.healthChecker != nil {
				am.healthChecker.AddTarget(c.ID, ip, port, healthConfig)
			}
		}

		adopted++
	}

	if adopted > 0 {
		am.updateNginxConfig(appName)
		log.Printf("Reconciled %d containers for %s", adopted, appName)
	}

	return adopted
}

// updateNginxConfig updates nginx configuration for an app
func (am *AppManager) updateNginxConfig(appName string) {
	am.lock.RLock()
	instances, exists := am.instances[appName]
	am.lock.RUnlock()

	if !exists || len(instances) == 0 {
		log.Printf("No instances for %s, removing nginx config", appName)
		am.nginx.RemoveAppConfig(appName)
		return
	}

	var healthyServers []Server
	for _, inst := range instances {
		if inst.State == "ready" {
			healthy := true
			if am.healthChecker != nil {
				healthy = am.healthChecker.IsHealthy(inst.ContainerID)
			}

			if healthy {
				healthyServers = append(healthyServers, Server{
					IP:   inst.IP,
					Port: inst.Port,
				})
			}
		}
	}

	if len(healthyServers) > 0 {
		log.Printf("Updating nginx for %s with %d healthy servers", appName, len(healthyServers))
		am.nginx.UpdateUpstreams(appName, healthyServers)
	} else {
		log.Printf("No healthy servers for %s, removing nginx config", appName)
		am.nginx.RemoveAppConfig(appName)
	}
}

// StartContainerMonitoring starts the monitoring goroutine
func (am *AppManager) StartContainerMonitoring() {
	if am.monitoringActive {
		log.Println("Container monitoring already active")
		return
	}

	ctx, cancel := context.WithCancel(am.ctx)
	am.monitoringCancel = cancel
	am.monitoringActive = true

	go am.containerMonitoringLoop(ctx)
	log.Println("Started container monitoring")
}

// StopContainerMonitoring stops the monitoring goroutine
func (am *AppManager) StopContainerMonitoring() {
	if am.monitoringCancel != nil {
		am.monitoringCancel()
	}
	am.monitoringActive = false
	log.Println("Stopped container monitoring")
}

// containerMonitoringLoop monitors container health
func (am *AppManager) containerMonitoringLoop(ctx context.Context) {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			am.checkAndRestartContainers()
			am.ensureMinReplicas()
		}
	}
}

// checkAndRestartContainers checks and restarts failed containers
func (am *AppManager) checkAndRestartContainers() {
	am.lock.RLock()
	appNames := make([]string, 0, len(am.instances))
	for name := range am.instances {
		appNames = append(appNames, name)
	}
	am.lock.RUnlock()

	for _, appName := range appNames {
		appRecord, _ := am.stateStore.GetApp(appName)
		if appRecord == nil {
			continue
		}

		am.lock.Lock()
		instancesToRestart := []*ContainerInstance{}
		indicesToRemove := []int{}

		for i, inst := range am.instances[appName] {
			containerJSON, err := am.client.ContainerInspect(am.ctx, inst.ContainerID)
			if err != nil || !containerJSON.State.Running {
				log.Printf("Container %s not running, marking for restart", inst.ContainerID[:12])
				indicesToRemove = append(indicesToRemove, i)
				instancesToRestart = append(instancesToRestart, inst)
			}
		}

		// Remove failed instances
		for i := len(indicesToRemove) - 1; i >= 0; i-- {
			idx := indicesToRemove[i]
			if idx < len(am.instances[appName]) {
				am.instances[appName] = append(am.instances[appName][:idx], am.instances[appName][idx+1:]...)
			}
		}
		am.lock.Unlock()

		// Recreate failed containers
		for range instancesToRestart {
			am.recreateContainer(appName, appRecord.Spec)
		}
	}
}

// recreateContainer recreates a failed container
func (am *AppManager) recreateContainer(appName string, appSpec map[string]interface{}) {
	am.lock.Lock()
	existingIndices := make(map[int]bool)
	for _, inst := range am.instances[appName] {
		c, err := am.client.ContainerInspect(am.ctx, inst.ContainerID)
		if err == nil {
			if idxStr := c.Config.Labels["orchestry.replica"]; idxStr != "" {
				if idx, err := strconv.Atoi(idxStr); err == nil {
					existingIndices[idx] = true
				}
			}
		}
	}

	nextIndex := 0
	for existingIndices[nextIndex] {
		nextIndex++
	}
	am.lock.Unlock()

	am.startContainer(appName, appSpec, nextIndex)
	am.updateNginxConfig(appName)
}

// ensureMinReplicas ensures apps maintain minimum replica count
func (am *AppManager) ensureMinReplicas() {
	apps, err := am.stateStore.ListApps()
	if err != nil {
		return
	}

	for _, app := range apps {
		if app.Status != "running" {
			continue
		}

		appRecord, _ := am.stateStore.GetApp(app.Name)
		if appRecord == nil {
			continue
		}

		scaling, _ := appRecord.Spec["scaling"].(map[string]interface{})
		minReplicas := 1
		if mr, ok := scaling["minReplicas"].(int); ok {
			minReplicas = mr
		} else if mr, ok := scaling["minReplicas"].(float64); ok {
			minReplicas = int(mr)
		}

		am.lock.RLock()
		currentCount := len(am.instances[app.Name])
		am.lock.RUnlock()

		if currentCount < minReplicas {
			needed := minReplicas - currentCount
			log.Printf("App %s has %d/%d replicas, creating %d more", app.Name, currentCount, minReplicas, needed)
			for i := 0; i < needed; i++ {
				am.recreateContainer(app.Name, appRecord.Spec)
			}
		}
	}
}

// Status returns the status of an application
func (am *AppManager) Status(appName string) map[string]interface{} {
	am.lock.RLock()
	instances := am.instances[appName]
	am.lock.RUnlock()

	if instances == nil {
		return map[string]interface{}{
			"error": "App not found or not running",
		}
	}

	readyCount := 0
	instancesList := []map[string]interface{}{}

	for _, inst := range instances {
		if inst.State == "ready" {
			readyCount++
		}

		instancesList = append(instancesList, map[string]interface{}{
			"container_id":   inst.ContainerID[:12],
			"ip":             inst.IP,
			"port":           inst.Port,
			"state":          inst.State,
			"cpu_percent":    inst.CPUPercent,
			"memory_percent": inst.MemoryPercent,
			"last_seen":      inst.LastSeen.Unix(),
			"failures":       inst.Failures,
		})
	}

	status := "running"
	if readyCount == 0 {
		status = "degraded"
	}

	return map[string]interface{}{
		"app":            appName,
		"status":         status,
		"replicas":       len(instances),
		"ready_replicas": readyCount,
		"instances":      instancesList,
	}
}

// Scale scales an application to the specified number of replicas
func (am *AppManager) Scale(appName string, targetReplicas int) map[string]interface{} {
	appRecord, err := am.stateStore.GetApp(appName)
	if err != nil {
		return map[string]interface{}{
			"error": fmt.Sprintf("App not found: %s", appName),
		}
	}

	am.lock.RLock()
	currentReplicas := len(am.instances[appName])
	am.lock.RUnlock()

	if currentReplicas == targetReplicas {
		return map[string]interface{}{
			"status":           "unchanged",
			"app":              appName,
			"current_replicas": currentReplicas,
			"target_replicas":  targetReplicas,
		}
	}

	if targetReplicas > currentReplicas {
		// Scale out - add containers
		needed := targetReplicas - currentReplicas
		for i := 0; i < needed; i++ {
			// Find next available index
			existingIndices := make(map[int]bool)
			am.lock.RLock()
			for _, inst := range am.instances[appName] {
				c, err := am.client.ContainerInspect(am.ctx, inst.ContainerID)
				if err == nil {
					if idxStr := c.Config.Labels["orchestry.replica"]; idxStr != "" {
						if idx, err := strconv.Atoi(idxStr); err == nil {
							existingIndices[idx] = true
						}
					}
				}
			}
			am.lock.RUnlock()

			nextIndex := 0
			for existingIndices[nextIndex] {
				nextIndex++
			}

			am.startContainer(appName, appRecord.Spec, nextIndex)
		}
	} else {
		// Scale in - remove containers
		toRemove := currentReplicas - targetReplicas
		am.lock.Lock()
		instancesToStop := am.instances[appName][len(am.instances[appName])-toRemove:]
		am.instances[appName] = am.instances[appName][:len(am.instances[appName])-toRemove]
		am.lock.Unlock()

		// Stop the containers
		for _, inst := range instancesToStop {
			if am.healthChecker != nil {
				am.healthChecker.RemoveTarget(inst.ContainerID)
			}

			timeout := 30
			am.client.ContainerStop(am.ctx, inst.ContainerID, container.StopOptions{
				Timeout: &timeout,
			})
			am.client.ContainerRemove(am.ctx, inst.ContainerID, types.ContainerRemoveOptions{
				Force: true,
			})
			log.Printf("Removed container %s for app %s", inst.ContainerID[:12], appName)
		}
	}

	// Update nginx config
	am.updateNginxConfig(appName)

	// Update app record
	appRecord.Replicas = targetReplicas
	appRecord.UpdatedAt = time.Now()
	am.stateStore.SaveApp(appRecord)

	return map[string]interface{}{
		"status":            "scaled",
		"app":               appName,
		"previous_replicas": currentReplicas,
		"target_replicas":   targetReplicas,
	}
}
