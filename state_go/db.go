package statego

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	_ "github.com/lib/pq"
)

// DatabaseError represents a database operation error
type DatabaseError struct {
	Message string
	Err     error
}

func (e *DatabaseError) Error() string {
	if e.Err != nil {
		return fmt.Sprintf("%s: %v", e.Message, e.Err)
	}
	return e.Message
}

// PostgreSQLManager manages PostgreSQL connections with HA support
type PostgreSQLManager struct {
	primaryDB            *sql.DB
	replicaDB            *sql.DB
	primaryDSN           string
	replicaDSN           string
	primaryFailed        bool
	lastPrimaryCheck     time.Time
	primaryCheckInterval time.Duration
	mu                   sync.RWMutex
}

// NewDatabaseManager creates a new PostgreSQL database manager with HA support
func NewDatabaseManager(primaryHost string, primaryPort int, replicaHost string, replicaPort int,
	database, username, password string, minConn, maxConn int) (*PostgreSQLManager, error) {

	// Build connection strings (without pool parameters - those are set via SetMaxOpenConns/SetMaxIdleConns)
	primaryDSN := fmt.Sprintf(
		"host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
		primaryHost, primaryPort, username, password, database,
	)

	replicaDSN := fmt.Sprintf(
		"host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
		replicaHost, replicaPort, username, password, database,
	)

	manager := &PostgreSQLManager{
		primaryDSN:           primaryDSN,
		replicaDSN:           replicaDSN,
		primaryCheckInterval: 30 * time.Second,
	}

	// Initialize connections
	if err := manager.initConnections(minConn, maxConn); err != nil {
		return nil, err
	}

	// Initialize database schema
	if err := manager.initDatabase(); err != nil {
		return nil, err
	}

	log.Println("🎉 PostgreSQL database schema initialized successfully")
	return manager, nil
}

// initConnections initializes primary and replica database connections
func (m *PostgreSQLManager) initConnections(minConn, maxConn int) error {
	var err error

	// Connect to primary
	m.primaryDB, err = sql.Open("postgres", m.primaryDSN)
	if err != nil {
		return &DatabaseError{Message: "Failed to connect to primary database", Err: err}
	}

	m.primaryDB.SetMaxOpenConns(maxConn)
	m.primaryDB.SetMaxIdleConns(minConn)
	m.primaryDB.SetConnMaxLifetime(time.Hour)

	// Test primary connection
	if err := m.primaryDB.Ping(); err != nil {
		log.Printf("⚠️  Primary database not available: %v", err)
		m.primaryFailed = true
		m.lastPrimaryCheck = time.Now()
	} else {
		log.Printf("✅ Connected to primary database")
	}

	// Connect to replica
	m.replicaDB, err = sql.Open("postgres", m.replicaDSN)
	if err != nil {
		log.Printf("⚠️  Failed to connect to replica database: %v", err)
		// Continue without replica
	} else {
		m.replicaDB.SetMaxOpenConns(maxConn)
		m.replicaDB.SetMaxIdleConns(minConn)
		m.replicaDB.SetConnMaxLifetime(time.Hour)

		if err := m.replicaDB.Ping(); err != nil {
			log.Printf("⚠️  Replica database not available: %v", err)
			m.replicaDB.Close()
			m.replicaDB = nil
		} else {
			log.Printf("✅ Connected to replica database")
		}
	}

	return nil
}

// initDatabase initializes the database schema
func (m *PostgreSQLManager) initDatabase() error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	// Create tables
	queries := []string{
		// Apps table
		`CREATE TABLE IF NOT EXISTS apps (
			name VARCHAR(255) PRIMARY KEY,
			spec JSONB NOT NULL,
			status VARCHAR(50) NOT NULL DEFAULT 'registered',
			created_at DOUBLE PRECISION NOT NULL,
			updated_at DOUBLE PRECISION NOT NULL,
			replicas INTEGER DEFAULT 0,
			last_scaled_at DOUBLE PRECISION,
			mode VARCHAR(10) DEFAULT 'auto'
		)`,

		// Instances table
		`CREATE TABLE IF NOT EXISTS instances (
			container_id VARCHAR(255) PRIMARY KEY,
			app_name VARCHAR(255) NOT NULL,
			ip VARCHAR(45) NOT NULL,
			port INTEGER NOT NULL,
			status VARCHAR(50) NOT NULL DEFAULT 'starting',
			created_at DOUBLE PRECISION NOT NULL,
			updated_at DOUBLE PRECISION NOT NULL,
			failure_count INTEGER DEFAULT 0,
			last_health_check DOUBLE PRECISION,
			FOREIGN KEY (app_name) REFERENCES apps (name) ON DELETE CASCADE
		)`,

		// Events table
		`CREATE TABLE IF NOT EXISTS events (
			id SERIAL PRIMARY KEY,
			app_name VARCHAR(255) NOT NULL,
			event_type VARCHAR(100) NOT NULL,
			message TEXT NOT NULL,
			timestamp DOUBLE PRECISION NOT NULL,
			details JSONB
		)`,

		// Scaling history table
		`CREATE TABLE IF NOT EXISTS scaling_history (
			id SERIAL PRIMARY KEY,
			app_name VARCHAR(255) NOT NULL,
			from_replicas INTEGER NOT NULL,
			to_replicas INTEGER NOT NULL,
			trigger_reason TEXT NOT NULL,
			metrics_snapshot JSONB,
			timestamp DOUBLE PRECISION NOT NULL
		)`,

		// Indexes
		`CREATE INDEX IF NOT EXISTS idx_events_app_time ON events (app_name, timestamp)`,
		`CREATE INDEX IF NOT EXISTS idx_events_type_time ON events (event_type, timestamp)`,
		`CREATE INDEX IF NOT EXISTS idx_apps_status ON apps (status)`,
		`CREATE INDEX IF NOT EXISTS idx_apps_mode ON apps (mode)`,
		`CREATE INDEX IF NOT EXISTS idx_instances_app ON instances (app_name)`,
		`CREATE INDEX IF NOT EXISTS idx_instances_status ON instances (status)`,
		`CREATE INDEX IF NOT EXISTS idx_scaling_app_time ON scaling_history (app_name, timestamp)`,
	}

	for _, query := range queries {
		if _, err := conn.ExecContext(ctx, query); err != nil {
			return &DatabaseError{Message: "Failed to initialize database schema", Err: err}
		}
	}

	return nil
}

// GetConnection returns the appropriate database pool for reads or writes (for DBManager interface)
func (m *PostgreSQLManager) GetConnection(write bool) (*sql.DB, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	// Check if we should retry primary connection
	if m.primaryFailed && time.Since(m.lastPrimaryCheck) > m.primaryCheckInterval {
		ctx := context.Background()
		m.mu.RUnlock()
		m.mu.Lock()
		m.checkPrimaryRecovery(ctx)
		m.mu.Unlock()
		m.mu.RLock()
	}

	if write {
		// For writes, return primary
		if !m.primaryFailed && m.primaryDB != nil {
			return m.primaryDB, nil
		}
		// Primary failed, return replica (emergency mode)
		if m.replicaDB != nil {
			log.Printf("🚨 USING REPLICA FOR WRITE OPERATION (PRIMARY DOWN)")
			return m.replicaDB, nil
		}
		return nil, &DatabaseError{Message: "❌ NO DATABASE AVAILABLE FOR WRITE OPERATIONS"}
	}

	// For reads, return replica first
	if m.replicaDB != nil {
		return m.replicaDB, nil
	}

	// Replica not available, return primary
	if !m.primaryFailed && m.primaryDB != nil {
		return m.primaryDB, nil
	}

	return nil, &DatabaseError{Message: "❌ NO DATABASE AVAILABLE FOR READ OPERATIONS"}
}

// getConnection returns a database connection with intelligent routing
func (m *PostgreSQLManager) getConnection(ctx context.Context, write bool) (*sql.Conn, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Check if we should retry primary connection
	if m.primaryFailed && time.Since(m.lastPrimaryCheck) > m.primaryCheckInterval {
		m.checkPrimaryRecovery(ctx)
	}

	if write {
		// For writes, try primary first
		if !m.primaryFailed && m.primaryDB != nil {
			conn, err := m.primaryDB.Conn(ctx)
			if err != nil {
				log.Printf("Primary database failed for write: %v", err)
				m.markPrimaryFailed()
			} else {
				return conn, nil
			}
		}

		// Primary failed, try replica for writes (emergency mode)
		if m.replicaDB != nil {
			log.Printf("🚨 USING REPLICA FOR WRITE OPERATION (PRIMARY DOWN)")
			conn, err := m.replicaDB.Conn(ctx)
			if err != nil {
				return nil, &DatabaseError{Message: "Replica also failed for write", Err: err}
			}
			return conn, nil
		}

		return nil, &DatabaseError{Message: "❌ NO DATABASE AVAILABLE FOR WRITE OPERATIONS"}
	}

	// For reads, try replica first
	if m.replicaDB != nil {
		conn, err := m.replicaDB.Conn(ctx)
		if err == nil {
			return conn, nil
		}
		log.Printf("⚠️  Replica failed for read, trying primary: %v", err)
	}

	// Replica failed, try primary for reads
	if !m.primaryFailed && m.primaryDB != nil {
		conn, err := m.primaryDB.Conn(ctx)
		if err != nil {
			log.Printf("Primary also failed for read: %v", err)
			m.markPrimaryFailed()
			return nil, &DatabaseError{Message: "Primary failed for read", Err: err}
		}
		return conn, nil
	}

	return nil, &DatabaseError{Message: "❌ NO DATABASE AVAILABLE FOR READ OPERATIONS"}
}

// markPrimaryFailed marks the primary database as failed
func (m *PostgreSQLManager) markPrimaryFailed() {
	m.primaryFailed = true
	m.lastPrimaryCheck = time.Now()
	log.Println("🚨 PRIMARY DATABASE MARKED AS FAILED")
}

// checkPrimaryRecovery checks if primary database has recovered
func (m *PostgreSQLManager) checkPrimaryRecovery(ctx context.Context) {
	if m.primaryDB == nil {
		return
	}

	if err := m.primaryDB.PingContext(ctx); err == nil {
		m.primaryFailed = false
		log.Println("✅ PRIMARY DATABASE RECOVERED")
	} else {
		log.Printf("Primary still failed: %v", err)
		m.lastPrimaryCheck = time.Now()
	}
}

// SaveApp saves or updates an application record
func (m *PostgreSQLManager) SaveApp(app *AppRecord) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	// Serialize spec to JSON
	specJSON, err := json.Marshal(app.Spec)
	if err != nil {
		return &DatabaseError{Message: "Failed to marshal app spec", Err: err}
	}

	query := `
		INSERT INTO apps (name, spec, status, created_at, updated_at, replicas, last_scaled_at, mode)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		ON CONFLICT (name) DO UPDATE SET
			spec = EXCLUDED.spec,
			status = EXCLUDED.status,
			updated_at = EXCLUDED.updated_at,
			replicas = EXCLUDED.replicas,
			last_scaled_at = EXCLUDED.last_scaled_at,
			mode = EXCLUDED.mode
	`

	_, err = conn.ExecContext(ctx, query,
		app.Name, specJSON, app.Status, app.CreatedAt, app.UpdatedAt,
		app.Replicas, app.LastScaledAt, app.Mode)

	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to save app %s", app.Name), Err: err}
	}

	return nil
}

// GetApp retrieves an application record by name
func (m *PostgreSQLManager) GetApp(name string) (*AppRecord, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, false)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	query := `SELECT name, spec, status, created_at, updated_at, replicas, last_scaled_at, mode FROM apps WHERE name = $1`

	var app AppRecord
	var specJSON []byte
	var mode sql.NullString

	err = conn.QueryRowContext(ctx, query, name).Scan(
		&app.Name, &specJSON, &app.Status, &app.CreatedAt, &app.UpdatedAt,
		&app.Replicas, &app.LastScaledAt, &mode,
	)

	if err == sql.ErrNoRows {
		return nil, nil
	}

	if err != nil {
		return nil, &DatabaseError{Message: fmt.Sprintf("Failed to get app %s", name), Err: err}
	}

	// Deserialize spec
	if err := json.Unmarshal(specJSON, &app.Spec); err != nil {
		return nil, &DatabaseError{Message: "Failed to unmarshal app spec", Err: err}
	}

	if mode.Valid {
		app.Mode = mode.String
	} else {
		app.Mode = "auto"
	}

	return &app, nil
}

// ListApps lists all applications, optionally filtered by status
func (m *PostgreSQLManager) ListApps(status string) ([]map[string]interface{}, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, false)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	var query string
	var rows *sql.Rows

	if status != "" {
		query = `SELECT name, spec, status, created_at, updated_at, replicas, last_scaled_at, mode FROM apps WHERE status = $1 ORDER BY name`
		rows, err = conn.QueryContext(ctx, query, status)
	} else {
		query = `SELECT name, spec, status, created_at, updated_at, replicas, last_scaled_at, mode FROM apps ORDER BY name`
		rows, err = conn.QueryContext(ctx, query)
	}

	if err != nil {
		return nil, &DatabaseError{Message: "Failed to list apps", Err: err}
	}
	defer rows.Close()

	apps := []map[string]interface{}{}

	for rows.Next() {
		var name, status string
		var specJSON []byte
		var createdAt, updatedAt float64
		var replicas int
		var lastScaledAt sql.NullFloat64
		var mode sql.NullString

		err := rows.Scan(&name, &specJSON, &status, &createdAt, &updatedAt, &replicas, &lastScaledAt, &mode)
		if err != nil {
			log.Printf("Failed to scan app row: %v", err)
			continue
		}

		var spec map[string]interface{}
		if err := json.Unmarshal(specJSON, &spec); err != nil {
			log.Printf("Failed to unmarshal spec for app %s: %v", name, err)
			continue
		}

		appMap := map[string]interface{}{
			"name":       name,
			"spec":       spec,
			"status":     status,
			"created_at": createdAt,
			"updated_at": updatedAt,
			"replicas":   replicas,
		}

		if lastScaledAt.Valid {
			appMap["last_scaled_at"] = lastScaledAt.Float64
		}

		if mode.Valid {
			appMap["mode"] = mode.String
		} else {
			appMap["mode"] = "auto"
		}

		apps = append(apps, appMap)
	}

	return apps, nil
}

// DeleteApp deletes an application and all its instances
func (m *PostgreSQLManager) DeleteApp(name string) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	// Delete instances first (foreign key constraint)
	_, err = conn.ExecContext(ctx, `DELETE FROM instances WHERE app_name = $1`, name)
	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to delete instances for app %s", name), Err: err}
	}

	// Delete the app
	result, err := conn.ExecContext(ctx, `DELETE FROM apps WHERE name = $1`, name)
	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to delete app %s", name), Err: err}
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		return &DatabaseError{Message: fmt.Sprintf("App %s not found", name)}
	}

	return nil
}

// UpdateAppStatus updates application status
func (m *PostgreSQLManager) UpdateAppStatus(name, status string) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	query := `UPDATE apps SET status = $1, updated_at = $2 WHERE name = $3`
	result, err := conn.ExecContext(ctx, query, status, TimeNow(), name)
	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to update app status %s", name), Err: err}
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		return &DatabaseError{Message: fmt.Sprintf("App %s not found", name)}
	}

	return nil
}

// UpdateAppReplicas updates application replica count
func (m *PostgreSQLManager) UpdateAppReplicas(name string, replicas int) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	now := TimeNow()
	query := `UPDATE apps SET replicas = $1, last_scaled_at = $2, updated_at = $3 WHERE name = $4`
	result, err := conn.ExecContext(ctx, query, replicas, now, now, name)
	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to update app replicas %s", name), Err: err}
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		return &DatabaseError{Message: fmt.Sprintf("App %s not found", name)}
	}

	return nil
}

// SaveInstance saves or updates a container instance record
func (m *PostgreSQLManager) SaveInstance(instance *InstanceRecord) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	query := `
		INSERT INTO instances (container_id, app_name, ip, port, status, created_at, updated_at, failure_count, last_health_check)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		ON CONFLICT (container_id) DO UPDATE SET
			app_name = EXCLUDED.app_name,
			ip = EXCLUDED.ip,
			port = EXCLUDED.port,
			status = EXCLUDED.status,
			updated_at = EXCLUDED.updated_at,
			failure_count = EXCLUDED.failure_count,
			last_health_check = EXCLUDED.last_health_check
	`

	_, err = conn.ExecContext(ctx, query,
		instance.ContainerID, instance.AppName, instance.IP, instance.Port,
		instance.Status, instance.CreatedAt, instance.UpdatedAt,
		instance.FailureCount, instance.LastHealthCheck)

	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to save instance %s", instance.ContainerID), Err: err}
	}

	return nil
}

// GetInstances retrieves instances for an application
func (m *PostgreSQLManager) GetInstances(appName, status string) ([]*InstanceRecord, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, false)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	var query string
	var rows *sql.Rows

	if status != "" {
		query = `SELECT container_id, app_name, ip, port, status, created_at, updated_at, failure_count, last_health_check FROM instances WHERE app_name = $1 AND status = $2`
		rows, err = conn.QueryContext(ctx, query, appName, status)
	} else {
		query = `SELECT container_id, app_name, ip, port, status, created_at, updated_at, failure_count, last_health_check FROM instances WHERE app_name = $1`
		rows, err = conn.QueryContext(ctx, query, appName)
	}

	if err != nil {
		return nil, &DatabaseError{Message: fmt.Sprintf("Failed to get instances for %s", appName), Err: err}
	}
	defer rows.Close()

	instances := []*InstanceRecord{}

	for rows.Next() {
		instance := &InstanceRecord{}
		err := rows.Scan(
			&instance.ContainerID, &instance.AppName, &instance.IP, &instance.Port,
			&instance.Status, &instance.CreatedAt, &instance.UpdatedAt,
			&instance.FailureCount, &instance.LastHealthCheck,
		)
		if err != nil {
			log.Printf("Failed to scan instance row: %v", err)
			continue
		}
		instances = append(instances, instance)
	}

	return instances, nil
}

// DeleteInstance deletes a container instance record
func (m *PostgreSQLManager) DeleteInstance(containerID string) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	result, err := conn.ExecContext(ctx, `DELETE FROM instances WHERE container_id = $1`, containerID)
	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to delete instance %s", containerID), Err: err}
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		return &DatabaseError{Message: fmt.Sprintf("Instance %s not found", containerID)}
	}

	return nil
}

// UpdateInstanceStatus updates instance status
func (m *PostgreSQLManager) UpdateInstanceStatus(containerID, status string) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	query := `UPDATE instances SET status = $1, updated_at = $2 WHERE container_id = $3`
	result, err := conn.ExecContext(ctx, query, status, TimeNow(), containerID)
	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to update instance status %s", containerID), Err: err}
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		return &DatabaseError{Message: fmt.Sprintf("Instance %s not found", containerID)}
	}

	return nil
}

// UpdateInstanceHealth updates instance health check results
func (m *PostgreSQLManager) UpdateInstanceHealth(containerID string, failureCount int) error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	now := TimeNow()
	query := `UPDATE instances SET failure_count = $1, last_health_check = $2, updated_at = $3 WHERE container_id = $4`
	result, err := conn.ExecContext(ctx, query, failureCount, now, now, containerID)
	if err != nil {
		return &DatabaseError{Message: fmt.Sprintf("Failed to update instance health %s", containerID), Err: err}
	}

	rowsAffected, _ := result.RowsAffected()
	if rowsAffected == 0 {
		return &DatabaseError{Message: fmt.Sprintf("Instance %s not found", containerID)}
	}

	return nil
}

// AddEvent adds a new event record
func (m *PostgreSQLManager) AddEvent(event *EventRecord) (int, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return 0, err
	}
	defer conn.Close()

	var detailsJSON []byte
	if event.Details != nil {
		detailsJSON, err = json.Marshal(event.Details)
		if err != nil {
			return 0, &DatabaseError{Message: "Failed to marshal event details", Err: err}
		}
	}

	query := `
		INSERT INTO events (app_name, event_type, message, timestamp, details)
		VALUES ($1, $2, $3, $4, $5)
		RETURNING id
	`

	var id int
	err = conn.QueryRowContext(ctx, query,
		event.AppName, event.EventType, event.Message, event.Timestamp, detailsJSON).Scan(&id)

	if err != nil {
		return 0, &DatabaseError{Message: "Failed to add event", Err: err}
	}

	return id, nil
}

// GetEvents retrieves events with optional filtering
func (m *PostgreSQLManager) GetEvents(appName, eventType string, limit int, since *float64) ([]map[string]interface{}, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, false)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	query := `SELECT id, app_name, event_type, message, timestamp, details FROM events WHERE 1=1`
	args := []interface{}{}
	argIdx := 1

	if appName != "" {
		query += fmt.Sprintf(" AND app_name = $%d", argIdx)
		args = append(args, appName)
		argIdx++
	}

	if eventType != "" {
		query += fmt.Sprintf(" AND event_type = $%d", argIdx)
		args = append(args, eventType)
		argIdx++
	}

	if since != nil {
		query += fmt.Sprintf(" AND timestamp >= $%d", argIdx)
		args = append(args, *since)
		argIdx++
	}

	query += fmt.Sprintf(" ORDER BY timestamp DESC LIMIT $%d", argIdx)
	args = append(args, limit)

	rows, err := conn.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, &DatabaseError{Message: "Failed to get events", Err: err}
	}
	defer rows.Close()

	events := []map[string]interface{}{}

	for rows.Next() {
		var id int
		var appName, eventType, message string
		var timestamp float64
		var detailsJSON []byte

		err := rows.Scan(&id, &appName, &eventType, &message, &timestamp, &detailsJSON)
		if err != nil {
			log.Printf("Failed to scan event row: %v", err)
			continue
		}

		event := map[string]interface{}{
			"id":         id,
			"app_name":   appName,
			"event_type": eventType,
			"message":    message,
			"timestamp":  timestamp,
		}

		if len(detailsJSON) > 0 {
			var details map[string]interface{}
			if err := json.Unmarshal(detailsJSON, &details); err == nil {
				event["details"] = details
			}
		}

		events = append(events, event)
	}

	return events, nil
}

// AddScalingEvent records a scaling event
func (m *PostgreSQLManager) AddScalingEvent(appName string, fromReplicas, toReplicas int, reason string, metricsSnapshot map[string]interface{}) (int, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return 0, err
	}
	defer conn.Close()

	var metricsJSON []byte
	if metricsSnapshot != nil {
		metricsJSON, err = json.Marshal(metricsSnapshot)
		if err != nil {
			return 0, &DatabaseError{Message: "Failed to marshal metrics snapshot", Err: err}
		}
	}

	query := `
		INSERT INTO scaling_history (app_name, from_replicas, to_replicas, trigger_reason, metrics_snapshot, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6)
		RETURNING id
	`

	var id int
	err = conn.QueryRowContext(ctx, query,
		appName, fromReplicas, toReplicas, reason, metricsJSON, TimeNow()).Scan(&id)

	if err != nil {
		return 0, &DatabaseError{Message: "Failed to add scaling event", Err: err}
	}

	return id, nil
}

// GetScalingHistory retrieves scaling history for an application
func (m *PostgreSQLManager) GetScalingHistory(appName string, limit int) ([]map[string]interface{}, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, false)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	query := `
		SELECT id, app_name, from_replicas, to_replicas, trigger_reason, metrics_snapshot, timestamp
		FROM scaling_history
		WHERE app_name = $1
		ORDER BY timestamp DESC
		LIMIT $2
	`

	rows, err := conn.QueryContext(ctx, query, appName, limit)
	if err != nil {
		return nil, &DatabaseError{Message: fmt.Sprintf("Failed to get scaling history for %s", appName), Err: err}
	}
	defer rows.Close()

	scalingEvents := []map[string]interface{}{}

	for rows.Next() {
		var id, fromReplicas, toReplicas int
		var appName, triggerReason string
		var timestamp float64
		var metricsJSON []byte

		err := rows.Scan(&id, &appName, &fromReplicas, &toReplicas, &triggerReason, &metricsJSON, &timestamp)
		if err != nil {
			log.Printf("Failed to scan scaling event row: %v", err)
			continue
		}

		event := map[string]interface{}{
			"id":             id,
			"app_name":       appName,
			"from_replicas":  fromReplicas,
			"to_replicas":    toReplicas,
			"trigger_reason": triggerReason,
			"timestamp":      timestamp,
		}

		if len(metricsJSON) > 0 {
			var metrics map[string]interface{}
			if err := json.Unmarshal(metricsJSON, &metrics); err == nil {
				event["metrics_snapshot"] = metrics
			}
		}

		scalingEvents = append(scalingEvents, event)
	}

	return scalingEvents, nil
}

// CleanupOldEvents cleans up old events
func (m *PostgreSQLManager) CleanupOldEvents(days int) (int, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return 0, err
	}
	defer conn.Close()

	cutoff := TimeNow() - float64(days*24*3600)

	result, err := conn.ExecContext(ctx, `DELETE FROM events WHERE timestamp < $1`, cutoff)
	if err != nil {
		return 0, &DatabaseError{Message: "Failed to cleanup old events", Err: err}
	}

	deleted, _ := result.RowsAffected()
	if deleted > 0 {
		log.Printf("Cleaned up %d old events", deleted)
	}

	return int(deleted), nil
}

// GetDatabaseStats retrieves database statistics
func (m *PostgreSQLManager) GetDatabaseStats() (map[string]interface{}, error) {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, false)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	stats := make(map[string]interface{})
	tables := []string{"apps", "instances", "events", "scaling_history"}

	for _, table := range tables {
		var count int
		query := fmt.Sprintf("SELECT COUNT(*) FROM %s", table)
		err := conn.QueryRowContext(ctx, query).Scan(&count)
		if err != nil {
			log.Printf("Failed to get count for table %s: %v", table, err)
			continue
		}
		stats[fmt.Sprintf("%s_count", table)] = count
	}

	return stats, nil
}

// Vacuum optimizes the database
func (m *PostgreSQLManager) Vacuum() error {
	ctx := context.Background()
	conn, err := m.getConnection(ctx, true)
	if err != nil {
		return err
	}
	defer conn.Close()

	_, err = conn.ExecContext(ctx, "VACUUM")
	if err != nil {
		return &DatabaseError{Message: "Failed to vacuum database", Err: err}
	}

	log.Println("Database vacuum completed")
	return nil
}

// Close closes database connections
func (m *PostgreSQLManager) Close() error {
	if m.primaryDB != nil {
		m.primaryDB.Close()
	}
	if m.replicaDB != nil {
		m.replicaDB.Close()
	}
	log.Println("🔒 Database connections closed")
	return nil
}

// Compatibility methods for API layer

// LogEvent logs an event (compatibility method)
func (m *PostgreSQLManager) LogEvent(appName, eventType string, details map[string]interface{}) error {
	event := &EventRecord{
		AppName:   appName,
		EventType: eventType,
		Message:   eventType,
		Timestamp: TimeNow(),
		Details:   details,
	}
	_, err := m.AddEvent(event)
	return err
}

// LogScalingAction logs a scaling action (compatibility method)
func (m *PostgreSQLManager) LogScalingAction(appName string, oldReplicas, newReplicas int, reason string, triggeredBy []string, metrics map[string]interface{}) error {
	fullReason := reason
	if len(triggeredBy) > 0 {
		fullReason = fmt.Sprintf("%s (triggered by: %v)", reason, triggeredBy)
	}

	_, err := m.AddScalingEvent(appName, oldReplicas, newReplicas, fullReason, metrics)
	return err
}

// GetRawSpec gets raw spec (compatibility method)
func (m *PostgreSQLManager) GetRawSpec(name string) (map[string]interface{}, error) {
	app, err := m.GetApp(name)
	if err != nil {
		return nil, err
	}
	if app == nil {
		return nil, nil
	}
	return app.Spec, nil
}
