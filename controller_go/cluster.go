package controller

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"sync"
	"time"

	"github.com/google/uuid"
	_ "github.com/lib/pq"
)

// NodeState represents the state of a cluster node
type NodeState string

const (
	NodeStateFollower  NodeState = "follower"
	NodeStateCandidate NodeState = "candidate"
	NodeStateLeader    NodeState = "leader"
	NodeStateStopped   NodeState = "stopped"
)

// ClusterNode represents a controller node in the cluster
type ClusterNode struct {
	NodeID        string     `json:"node_id"`
	Hostname      string     `json:"hostname"`
	Port          int        `json:"port"`
	APIURL        string     `json:"api_url"`
	State         NodeState  `json:"state"`
	LastHeartbeat time.Time  `json:"last_heartbeat"`
	LeaseExpires  *time.Time `json:"lease_expires_at,omitempty"`
	Term          int        `json:"term"`
	VotesReceived int        `json:"votes_received"`
	IsHealthy     bool       `json:"is_healthy"`
}

// LeaderLease represents leader lease information
type LeaderLease struct {
	LeaderID   string    `json:"leader_id"`
	Term       int       `json:"term"`
	AcquiredAt time.Time `json:"acquired_at"`
	ExpiresAt  time.Time `json:"expires_at"`
	RenewedAt  time.Time `json:"renewed_at"`
	Hostname   string    `json:"hostname"`
	APIURL     string    `json:"api_url"`
}

// DBManager interface for database operations
type DBManager interface {
	GetConnection(write bool) (*sql.DB, error)
}

// EventCallback function types
type EventCallback func()
type ClusterChangeCallback func(map[string]*ClusterNode)

// DistributedController manages distributed controller cluster with leader election
type DistributedController struct {
	// Node identification
	nodeID         string
	hostname       string
	port           int
	apiURL         string
	externalAPIURL string

	// Cluster state
	state       NodeState
	currentTerm int
	votedFor    *string
	leaderID    *string
	isLeader    bool

	// Database connection
	dbManager DBManager
	lock      sync.RWMutex

	// Timing configuration
	leaseTTL          int
	heartbeatInterval int
	electionTimeout   int

	// Background tasks
	running bool
	ctx     context.Context
	cancel  context.CancelFunc
	wg      sync.WaitGroup

	// Event callbacks
	onBecomeLeader   EventCallback
	onLoseLeadership EventCallback
	onClusterChange  ClusterChangeCallback

	// Cluster membership
	clusterNodes map[string]*ClusterNode
	nodesLock    sync.RWMutex
}

// NewDistributedController creates a new distributed controller instance
func NewDistributedController(
	nodeID string,
	hostname string,
	port int,
	dbManager DBManager,
	leaseTTL int,
	heartbeatInterval int,
	electionTimeout int,
) (*DistributedController, error) {

	if nodeID == "" {
		nodeID = uuid.New().String()
	}

	if hostname == "" {
		hostname, _ = os.Hostname()
	}

	if leaseTTL == 0 {
		leaseTTL = 30
	}
	if heartbeatInterval == 0 {
		heartbeatInterval = 10
	}
	if electionTimeout == 0 {
		electionTimeout = 15
	}

	apiURL := fmt.Sprintf("http://%s:%d", hostname, port)

	// External API URL for client redirects
	controllerLBHost := os.Getenv("CONTROLLER_LB_HOST")
	if controllerLBHost == "" {
		controllerLBHost = "localhost"
	}
	controllerLBPort := os.Getenv("CONTROLLER_LB_PORT")
	if controllerLBPort == "" {
		controllerLBPort = "8000"
	}
	externalAPIURL := fmt.Sprintf("http://%s:%s", controllerLBHost, controllerLBPort)

	dc := &DistributedController{
		nodeID:            nodeID,
		hostname:          hostname,
		port:              port,
		apiURL:            apiURL,
		externalAPIURL:    externalAPIURL,
		state:             NodeStateFollower,
		currentTerm:       0,
		dbManager:         dbManager,
		leaseTTL:          leaseTTL,
		heartbeatInterval: heartbeatInterval,
		electionTimeout:   electionTimeout,
		clusterNodes:      make(map[string]*ClusterNode),
	}

	log.Printf("🏗️  Initializing distributed controller node %s", dc.nodeID)
	log.Printf("📍 Node: %s:%d -> %s", dc.hostname, dc.port, dc.apiURL)

	return dc, nil
}

// Start starts the distributed controller cluster
func (dc *DistributedController) Start() error {
	if dc.running {
		log.Println("Cluster node already running")
		return nil
	}

	log.Println("🚀 Starting distributed controller cluster...")

	// Initialize database tables
	if err := dc.initClusterTables(); err != nil {
		return fmt.Errorf("failed to initialize cluster tables: %w", err)
	}

	// Register this node
	if err := dc.registerNode(); err != nil {
		return fmt.Errorf("failed to register node: %w", err)
	}

	// Start background tasks
	dc.running = true
	dc.ctx, dc.cancel = context.WithCancel(context.Background())
	dc.startBackgroundTasks()

	log.Printf("✅ Distributed controller node %s started", dc.nodeID)
	return nil
}

// Stop stops the distributed controller cluster
func (dc *DistributedController) Stop() {
	if !dc.running {
		return
	}

	log.Println("🛑 Stopping distributed controller cluster...")
	dc.running = false

	// Release leadership if we're the leader
	if dc.isLeader {
		dc.releaseLeadership()
	}

	// Mark node as stopped
	dc.state = NodeStateStopped
	dc.updateNodeStatus()

	// Cancel context and wait for goroutines
	if dc.cancel != nil {
		dc.cancel()
	}
	dc.wg.Wait()

	log.Printf("Distributed controller node %s stopped", dc.nodeID)
}

// initClusterTables initializes database tables for cluster coordination
func (dc *DistributedController) initClusterTables() error {
	log.Println("Initializing cluster coordination tables...")

	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		return err
	}

	queries := []string{
		// Cluster nodes table
		`CREATE TABLE IF NOT EXISTS cluster_nodes (
			node_id VARCHAR(255) PRIMARY KEY,
			hostname VARCHAR(255) NOT NULL,
			port INTEGER NOT NULL,
			api_url VARCHAR(512) NOT NULL,
			state VARCHAR(50) NOT NULL,
			term INTEGER NOT NULL DEFAULT 0,
			last_heartbeat TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			is_healthy BOOLEAN NOT NULL DEFAULT true,
			created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
		)`,

		// Leader lease table
		`CREATE TABLE IF NOT EXISTS leader_lease (
			id INTEGER PRIMARY KEY DEFAULT 1,
			leader_id VARCHAR(255) NOT NULL,
			term INTEGER NOT NULL,
			acquired_at TIMESTAMP NOT NULL,
			expires_at TIMESTAMP NOT NULL,
			renewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
			hostname VARCHAR(255) NOT NULL,
			api_url VARCHAR(512) NOT NULL,
			CONSTRAINT single_lease CHECK (id = 1)
		)`,

		// Cluster events table
		`CREATE TABLE IF NOT EXISTS cluster_events (
			id SERIAL PRIMARY KEY,
			node_id VARCHAR(255) NOT NULL,
			event_type VARCHAR(100) NOT NULL,
			event_data JSONB,
			term INTEGER NOT NULL,
			timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
		)`,

		// Indices
		`CREATE INDEX IF NOT EXISTS idx_cluster_nodes_state ON cluster_nodes(state)`,
		`CREATE INDEX IF NOT EXISTS idx_cluster_nodes_heartbeat ON cluster_nodes(last_heartbeat)`,
		`CREATE INDEX IF NOT EXISTS idx_cluster_events_node_term ON cluster_events(node_id, term)`,
		`CREATE INDEX IF NOT EXISTS idx_cluster_events_timestamp ON cluster_events(timestamp)`,
	}

	for _, query := range queries {
		if _, err := db.Exec(query); err != nil {
			return fmt.Errorf("failed to execute query: %w", err)
		}
	}

	log.Println("Cluster coordination tables initialized")
	return nil
}

// registerNode registers this node in the cluster
func (dc *DistributedController) registerNode() error {
	log.Printf("📝 Registering node %s in cluster...", dc.nodeID)

	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		return err
	}

	query := `
		INSERT INTO cluster_nodes
		(node_id, hostname, port, api_url, state, term, last_heartbeat, is_healthy)
		VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP, $7)
		ON CONFLICT (node_id) DO UPDATE SET
			hostname = EXCLUDED.hostname,
			port = EXCLUDED.port,
			api_url = EXCLUDED.api_url,
			state = EXCLUDED.state,
			term = EXCLUDED.term,
			last_heartbeat = CURRENT_TIMESTAMP,
			is_healthy = EXCLUDED.is_healthy,
			updated_at = CURRENT_TIMESTAMP
	`

	_, err = db.Exec(query,
		dc.nodeID,
		dc.hostname,
		dc.port,
		dc.apiURL,
		dc.state,
		dc.currentTerm,
		true,
	)

	if err != nil {
		log.Printf("❌ Failed to register node: %v", err)
		return err
	}

	log.Printf("✅ Node %s registered in cluster", dc.nodeID)
	return nil
}

// startBackgroundTasks starts background monitoring tasks
func (dc *DistributedController) startBackgroundTasks() {
	// Heartbeat task
	dc.wg.Add(1)
	go dc.heartbeatLoop()

	// Election task
	dc.wg.Add(1)
	go dc.electionLoop()

	// Cluster monitoring task
	dc.wg.Add(1)
	go dc.clusterMonitorLoop()
}

// heartbeatLoop maintains node presence
func (dc *DistributedController) heartbeatLoop() {
	defer dc.wg.Done()
	log.Println("💓 Starting heartbeat loop...")

	ticker := time.NewTicker(time.Duration(dc.heartbeatInterval) * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-dc.ctx.Done():
			return
		case <-ticker.C:
			dc.sendHeartbeat()

			// If we're the leader, renew our lease
			if dc.isLeader {
				dc.renewLeadershipLease()
			}
		}
	}
}

// electionLoop monitors elections and leadership
func (dc *DistributedController) electionLoop() {
	defer dc.wg.Done()
	log.Println("🗳️  Starting election monitoring loop...")

	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-dc.ctx.Done():
			return
		case <-ticker.C:
			if !dc.isLeader {
				if dc.shouldStartElection() {
					dc.startLeaderElection()
				}
			}

			dc.checkLeaderHealth()
		}
	}
}

// clusterMonitorLoop monitors cluster membership
func (dc *DistributedController) clusterMonitorLoop() {
	defer dc.wg.Done()
	log.Println("🔍 Starting cluster monitoring loop...")

	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-dc.ctx.Done():
			return
		case <-ticker.C:
			dc.updateClusterMembership()
			dc.cleanupStaleNodes()
		}
	}
}

// sendHeartbeat sends heartbeat to update node status
func (dc *DistributedController) sendHeartbeat() {
	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		log.Printf("❌ Failed to get DB connection for heartbeat: %v", err)
		return
	}

	query := `
		UPDATE cluster_nodes 
		SET last_heartbeat = CURRENT_TIMESTAMP,
			state = $1,
			term = $2,
			is_healthy = $3,
			updated_at = CURRENT_TIMESTAMP
		WHERE node_id = $4
	`

	dc.lock.RLock()
	state := dc.state
	term := dc.currentTerm
	dc.lock.RUnlock()

	_, err = db.Exec(query, state, term, true, dc.nodeID)
	if err != nil {
		log.Printf("❌ Failed to send heartbeat: %v", err)
	}
}

// shouldStartElection checks if we should start an election
func (dc *DistributedController) shouldStartElection() bool {
	lease := dc.getCurrentLease()
	if lease != nil && lease.ExpiresAt.After(time.Now()) {
		// Valid leader exists
		dc.lock.Lock()
		if dc.leaderID == nil || *dc.leaderID != lease.LeaderID {
			dc.leaderID = &lease.LeaderID
			log.Printf("👑 Acknowledged leader: %s", lease.LeaderID)
		}
		dc.lock.Unlock()
		return false
	}

	// No valid leader - check if we should start election
	dc.lock.RLock()
	state := dc.state
	dc.lock.RUnlock()

	if state == NodeStateFollower {
		log.Println("🗳️  No valid leader found, considering election...")
		return true
	}

	return false
}

// startLeaderElection starts a leader election process
func (dc *DistributedController) startLeaderElection() {
	dc.lock.Lock()
	if dc.state != NodeStateFollower {
		dc.lock.Unlock()
		return
	}

	log.Printf("🚀 Starting leader election for term %d", dc.currentTerm+1)

	// Become candidate
	dc.state = NodeStateCandidate
	dc.currentTerm++
	dc.votedFor = &dc.nodeID
	currentTerm := dc.currentTerm
	dc.lock.Unlock()

	// Try to acquire leadership lease
	if dc.tryAcquireLeadership(currentTerm) {
		dc.becomeLeader()
	} else {
		dc.lock.Lock()
		dc.state = NodeStateFollower
		dc.votedFor = nil
		dc.lock.Unlock()
		log.Printf("❌ Failed to acquire leadership lease for term %d", currentTerm)
	}
}

// tryAcquireLeadership tries to acquire leadership lease atomically
func (dc *DistributedController) tryAcquireLeadership(term int) bool {
	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		return false
	}

	query := `
		INSERT INTO leader_lease 
		(id, leader_id, term, acquired_at, expires_at, renewed_at, hostname, api_url)
		VALUES (1, $1, $2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '%d seconds', CURRENT_TIMESTAMP, $3, $4)
		ON CONFLICT (id) DO UPDATE SET
			leader_id = EXCLUDED.leader_id,
			term = EXCLUDED.term,
			acquired_at = CURRENT_TIMESTAMP,
			expires_at = CURRENT_TIMESTAMP + INTERVAL '%d seconds',
			renewed_at = CURRENT_TIMESTAMP,
			hostname = EXCLUDED.hostname,
			api_url = EXCLUDED.api_url
		WHERE leader_lease.expires_at <= CURRENT_TIMESTAMP 
		   OR leader_lease.term < EXCLUDED.term
	`

	query = fmt.Sprintf(query, dc.leaseTTL, dc.leaseTTL)

	result, err := db.Exec(query, dc.nodeID, term, dc.hostname, dc.apiURL)
	if err != nil {
		log.Printf("❌ Failed to acquire leadership lease: %v", err)
		return false
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected > 0 {
		log.Printf("✅ Acquired leadership lease for term %d", term)
		return true
	}

	return false
}

// becomeLeader transitions to leader state
func (dc *DistributedController) becomeLeader() {
	dc.lock.Lock()
	log.Printf("👑 Becoming cluster leader (term %d)", dc.currentTerm)

	dc.state = NodeStateLeader
	dc.isLeader = true
	dc.leaderID = &dc.nodeID
	term := dc.currentTerm
	dc.lock.Unlock()

	// Update node status
	dc.updateNodeStatus()

	// Log cluster event
	dc.logClusterEvent("leader_elected", map[string]interface{}{
		"term":     term,
		"node_id":  dc.nodeID,
		"hostname": dc.hostname,
	})

	// Notify application
	if dc.onBecomeLeader != nil {
		go func() {
			defer func() {
				if r := recover(); r != nil {
					log.Printf("❌ Panic in become_leader callback: %v", r)
				}
			}()
			dc.onBecomeLeader()
		}()
	}

	log.Println("👑 Successfully became cluster leader")
}

// loseLeadership loses leadership
func (dc *DistributedController) loseLeadership() {
	dc.lock.Lock()
	if !dc.isLeader {
		dc.lock.Unlock()
		return
	}

	log.Println("💔 Losing cluster leadership")

	dc.state = NodeStateFollower
	dc.isLeader = false
	dc.leaderID = nil
	term := dc.currentTerm
	dc.lock.Unlock()

	// Update node status
	dc.updateNodeStatus()

	// Log cluster event
	dc.logClusterEvent("leader_lost", map[string]interface{}{
		"term":    term,
		"node_id": dc.nodeID,
		"reason":  "lease_expired",
	})

	// Notify application
	if dc.onLoseLeadership != nil {
		go func() {
			defer func() {
				if r := recover(); r != nil {
					log.Printf("❌ Panic in lose_leadership callback: %v", r)
				}
			}()
			dc.onLoseLeadership()
		}()
	}

	log.Println("💔 Lost cluster leadership")
}

// releaseLeadership voluntarily releases leadership
func (dc *DistributedController) releaseLeadership() {
	dc.lock.RLock()
	if !dc.isLeader {
		dc.lock.RUnlock()
		return
	}
	term := dc.currentTerm
	dc.lock.RUnlock()

	log.Println("🚪 Voluntarily releasing cluster leadership")

	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		return
	}

	query := `DELETE FROM leader_lease WHERE leader_id = $1 AND term = $2`
	_, err = db.Exec(query, dc.nodeID, term)
	if err != nil {
		log.Printf("❌ Failed to release leadership lease: %v", err)
	}

	dc.loseLeadership()
}

// renewLeadershipLease renews leadership lease
func (dc *DistributedController) renewLeadershipLease() {
	dc.lock.RLock()
	if !dc.isLeader {
		dc.lock.RUnlock()
		return
	}
	term := dc.currentTerm
	dc.lock.RUnlock()

	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		dc.loseLeadership()
		return
	}

	query := fmt.Sprintf(`
		UPDATE leader_lease 
		SET expires_at = CURRENT_TIMESTAMP + INTERVAL '%d seconds',
			renewed_at = CURRENT_TIMESTAMP
		WHERE leader_id = $1 AND term = $2
	`, dc.leaseTTL)

	result, err := db.Exec(query, dc.nodeID, term)
	if err != nil {
		log.Printf("❌ Failed to renew leadership lease: %v", err)
		dc.loseLeadership()
		return
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		log.Println("⚠️  Lost leadership lease during renewal")
		dc.loseLeadership()
	}
}

// checkLeaderHealth checks current leader health
func (dc *DistributedController) checkLeaderHealth() {
	lease := dc.getCurrentLease()
	if lease == nil {
		return
	}

	now := time.Now()

	// Check if lease has expired
	if lease.ExpiresAt.Before(now) || lease.ExpiresAt.Equal(now) {
		dc.lock.Lock()
		if dc.leaderID != nil && *dc.leaderID == lease.LeaderID {
			dc.leaderID = nil
			log.Println("⏰ Leader lease expired")
		}
		dc.lock.Unlock()
		return
	}

	// Update our knowledge of current leader
	dc.lock.Lock()
	if dc.leaderID == nil || *dc.leaderID != lease.LeaderID {
		dc.leaderID = &lease.LeaderID
		log.Printf("👑 New leader detected: %s", lease.LeaderID)
	}
	dc.lock.Unlock()
}

// getCurrentLease gets current leadership lease
func (dc *DistributedController) getCurrentLease() *LeaderLease {
	db, err := dc.dbManager.GetConnection(false)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		return nil
	}

	query := `
		SELECT leader_id, term, acquired_at, expires_at, 
		       renewed_at, hostname, api_url
		FROM leader_lease 
		WHERE id = 1
	`

	var lease LeaderLease
	err = db.QueryRow(query).Scan(
		&lease.LeaderID,
		&lease.Term,
		&lease.AcquiredAt,
		&lease.ExpiresAt,
		&lease.RenewedAt,
		&lease.Hostname,
		&lease.APIURL,
	)

	if err != nil {
		if err != sql.ErrNoRows {
			log.Printf("❌ Failed to get current lease: %v", err)
		}
		return nil
	}

	return &lease
}

// updateClusterMembership updates knowledge of cluster members
func (dc *DistributedController) updateClusterMembership() {
	db, err := dc.dbManager.GetConnection(false)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		return
	}

	query := `
		SELECT node_id, hostname, port, api_url, state, 
		       term, last_heartbeat, is_healthy
		FROM cluster_nodes
		WHERE last_heartbeat >= CURRENT_TIMESTAMP - INTERVAL '60 seconds'
	`

	rows, err := db.Query(query)
	if err != nil {
		log.Printf("❌ Failed to query cluster nodes: %v", err)
		return
	}
	defer rows.Close()

	newNodes := make(map[string]*ClusterNode)
	for rows.Next() {
		var node ClusterNode
		var state string

		err := rows.Scan(
			&node.NodeID,
			&node.Hostname,
			&node.Port,
			&node.APIURL,
			&state,
			&node.Term,
			&node.LastHeartbeat,
			&node.IsHealthy,
		)
		if err != nil {
			log.Printf("❌ Failed to scan cluster node: %v", err)
			continue
		}

		node.State = NodeState(state)
		newNodes[node.NodeID] = &node
	}

	// Compare with existing nodes
	dc.nodesLock.Lock()
	oldNodes := make(map[string]bool)
	for id := range dc.clusterNodes {
		oldNodes[id] = true
	}

	newNodeIDs := make(map[string]bool)
	for id := range newNodes {
		newNodeIDs[id] = true
	}

	// Detect changes
	var added, removed []string
	for id := range newNodeIDs {
		if !oldNodes[id] {
			added = append(added, id)
		}
	}
	for id := range oldNodes {
		if !newNodeIDs[id] {
			removed = append(removed, id)
		}
	}

	changed := len(added) > 0 || len(removed) > 0
	if changed {
		dc.clusterNodes = newNodes

		if len(added) > 0 {
			log.Printf("➕ Cluster nodes joined: %v", added)
		}
		if len(removed) > 0 {
			log.Printf("➖ Cluster nodes left: %v", removed)
		}

		// Make a copy for callback
		nodesCopy := make(map[string]*ClusterNode)
		for k, v := range dc.clusterNodes {
			nodesCopy[k] = v
		}
		dc.nodesLock.Unlock()

		// Notify of cluster change
		if dc.onClusterChange != nil {
			go func() {
				defer func() {
					if r := recover(); r != nil {
						log.Printf("❌ Panic in cluster_change callback: %v", r)
					}
				}()
				dc.onClusterChange(nodesCopy)
			}()
		}
	} else {
		dc.nodesLock.Unlock()
	}
}

// cleanupStaleNodes removes stale nodes from cluster
func (dc *DistributedController) cleanupStaleNodes() {
	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		return
	}

	query := `
		DELETE FROM cluster_nodes
		WHERE last_heartbeat < CURRENT_TIMESTAMP - INTERVAL '300 seconds'
		  AND node_id != $1
	`

	result, err := db.Exec(query, dc.nodeID)
	if err != nil {
		log.Printf("❌ Failed to cleanup stale nodes: %v", err)
		return
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected > 0 {
		log.Printf("🧹 Cleaned up %d stale cluster nodes", rowsAffected)
	}
}

// updateNodeStatus updates this node's status
func (dc *DistributedController) updateNodeStatus() {
	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		return
	}

	dc.lock.RLock()
	state := dc.state
	term := dc.currentTerm
	dc.lock.RUnlock()

	query := `
		UPDATE cluster_nodes 
		SET state = $1, 
			term = $2,
			updated_at = CURRENT_TIMESTAMP
		WHERE node_id = $3
	`

	_, err = db.Exec(query, state, term, dc.nodeID)
	if err != nil {
		log.Printf("❌ Failed to update node status: %v", err)
	}
}

// logClusterEvent logs cluster coordination event
func (dc *DistributedController) logClusterEvent(eventType string, eventData map[string]interface{}) {
	db, err := dc.dbManager.GetConnection(true)
	if err != nil {
		log.Printf("❌ Failed to get DB connection: %v", err)
		return
	}

	dc.lock.RLock()
	term := dc.currentTerm
	dc.lock.RUnlock()

	eventJSON, err := json.Marshal(eventData)
	if err != nil {
		log.Printf("❌ Failed to marshal event data: %v", err)
		return
	}

	query := `
		INSERT INTO cluster_events (node_id, event_type, event_data, term)
		VALUES ($1, $2, $3, $4)
	`

	_, err = db.Exec(query, dc.nodeID, eventType, eventJSON, term)
	if err != nil {
		log.Printf("❌ Failed to log cluster event: %v", err)
	}
}

// SetOnBecomeLeader sets the callback for becoming leader
func (dc *DistributedController) SetOnBecomeLeader(callback EventCallback) {
	dc.onBecomeLeader = callback
}

// SetOnLoseLeadership sets the callback for losing leadership
func (dc *DistributedController) SetOnLoseLeadership(callback EventCallback) {
	dc.onLoseLeadership = callback
}

// SetOnClusterChange sets the callback for cluster changes
func (dc *DistributedController) SetOnClusterChange(callback ClusterChangeCallback) {
	dc.onClusterChange = callback
}

// GetClusterStatus returns current cluster status
func (dc *DistributedController) GetClusterStatus() map[string]interface{} {
	dc.lock.RLock()
	nodeID := dc.nodeID
	hostname := dc.hostname
	state := dc.state
	term := dc.currentTerm
	isLeader := dc.isLeader
	var leaderID *string
	if dc.leaderID != nil {
		lid := *dc.leaderID
		leaderID = &lid
	}
	dc.lock.RUnlock()

	dc.nodesLock.RLock()
	clusterSize := len(dc.clusterNodes)
	nodes := make([]*ClusterNode, 0, clusterSize)
	for _, node := range dc.clusterNodes {
		nodes = append(nodes, node)
	}
	dc.nodesLock.RUnlock()

	lease := dc.getCurrentLease()

	status := map[string]interface{}{
		"node_id":      nodeID,
		"hostname":     hostname,
		"state":        state,
		"term":         term,
		"is_leader":    isLeader,
		"cluster_size": clusterSize,
		"nodes":        nodes,
	}

	if leaderID != nil {
		status["leader_id"] = *leaderID
	}

	if lease != nil {
		status["lease"] = lease
	}

	return status
}

// GetLeaderInfo returns current leader information
func (dc *DistributedController) GetLeaderInfo() map[string]interface{} {
	lease := dc.getCurrentLease()
	if lease != nil && lease.ExpiresAt.After(time.Now()) {
		return map[string]interface{}{
			"leader_id":        lease.LeaderID,
			"hostname":         lease.Hostname,
			"api_url":          lease.APIURL,
			"external_api_url": dc.externalAPIURL,
			"term":             lease.Term,
			"lease_expires_at": lease.ExpiresAt,
		}
	}
	return nil
}

// IsClusterReady checks if cluster has minimum nodes and a leader
func (dc *DistributedController) IsClusterReady() bool {
	dc.nodesLock.RLock()
	nodeCount := len(dc.clusterNodes)
	dc.nodesLock.RUnlock()

	dc.lock.RLock()
	hasLeader := dc.leaderID != nil
	dc.lock.RUnlock()

	lease := dc.getCurrentLease()

	return nodeCount >= 1 && hasLeader && lease != nil
}

// IsLeader returns whether this node is the current leader
func (dc *DistributedController) IsLeader() bool {
	dc.lock.RLock()
	defer dc.lock.RUnlock()
	return dc.isLeader
}

// GetNodeID returns the node ID
func (dc *DistributedController) GetNodeID() string {
	return dc.nodeID
}

// GetLeaderID returns the current leader ID
func (dc *DistributedController) GetLeaderID() *string {
	dc.lock.RLock()
	defer dc.lock.RUnlock()
	if dc.leaderID != nil {
		lid := *dc.leaderID
		return &lid
	}
	return nil
}
