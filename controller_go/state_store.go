package controller

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"time"
)

// PostgresStateStore implements state storage using PostgreSQL
type PostgresStateStore struct {
	dbManager DBManager
}

// NewPostgresStateStore creates a new PostgresStateStore instance
func NewPostgresStateStore(dbManager DBManager) *PostgresStateStore {
	return &PostgresStateStore{
		dbManager: dbManager,
	}
}

// GetApp retrieves an application record by name
func (s *PostgresStateStore) GetApp(name string) (*AppRecord, error) {
	db, err := s.dbManager.GetConnection(false) // read-only
	if err != nil {
		return nil, fmt.Errorf("failed to get database connection: %w", err)
	}

	query := `
		SELECT name, spec, status, created_at, updated_at, replicas, mode
		FROM apps
		WHERE name = $1
	`

	var app AppRecord
	var specJSON []byte
	var createdAtFloat, updatedAtFloat float64

	err = db.QueryRow(query, name).Scan(
		&app.Name,
		&specJSON,
		&app.Status,
		&createdAtFloat,
		&updatedAtFloat,
		&app.Replicas,
		&app.Mode,
	)

	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("app not found: %s", name)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to query app: %w", err)
	}

	// Parse spec JSON
	if err := json.Unmarshal(specJSON, &app.Spec); err != nil {
		return nil, fmt.Errorf("failed to parse spec: %w", err)
	}

	app.CreatedAt = time.Unix(int64(createdAtFloat), 0)
	app.UpdatedAt = time.Unix(int64(updatedAtFloat), 0)

	return &app, nil
}

// SaveApp saves or updates an application record
func (s *PostgresStateStore) SaveApp(record *AppRecord) error {
	db, err := s.dbManager.GetConnection(true) // write
	if err != nil {
		return fmt.Errorf("failed to get database connection: %w", err)
	}

	specJSON, err := json.Marshal(record.Spec)
	if err != nil {
		return fmt.Errorf("failed to marshal spec: %w", err)
	}

	query := `
		INSERT INTO apps (name, spec, status, created_at, updated_at, replicas, mode)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		ON CONFLICT (name) DO UPDATE SET
			spec = $2,
			status = $3,
			updated_at = $5,
			replicas = $6,
			mode = $7
	`

	createdAt := record.CreatedAt.Unix()
	updatedAt := record.UpdatedAt.Unix()

	_, err = db.Exec(query,
		record.Name,
		specJSON,
		record.Status,
		createdAt,
		updatedAt,
		record.Replicas,
		record.Mode,
	)

	if err != nil {
		return fmt.Errorf("failed to save app: %w", err)
	}

	return nil
}

// ListApps returns all registered applications
func (s *PostgresStateStore) ListApps() ([]*AppRecord, error) {
	db, err := s.dbManager.GetConnection(false) // read-only
	if err != nil {
		return nil, fmt.Errorf("failed to get database connection: %w", err)
	}

	query := `
		SELECT name, spec, status, created_at, updated_at, replicas, mode
		FROM apps
		ORDER BY name
	`

	rows, err := db.Query(query)
	if err != nil {
		return nil, fmt.Errorf("failed to query apps: %w", err)
	}
	defer rows.Close()

	apps := []*AppRecord{}
	for rows.Next() {
		var app AppRecord
		var specJSON []byte
		var createdAtFloat, updatedAtFloat float64

		err := rows.Scan(
			&app.Name,
			&specJSON,
			&app.Status,
			&createdAtFloat,
			&updatedAtFloat,
			&app.Replicas,
			&app.Mode,
		)
		if err != nil {
			return nil, fmt.Errorf("failed to scan app: %w", err)
		}

		// Parse spec JSON
		if err := json.Unmarshal(specJSON, &app.Spec); err != nil {
			return nil, fmt.Errorf("failed to parse spec: %w", err)
		}

		app.CreatedAt = time.Unix(int64(createdAtFloat), 0)
		app.UpdatedAt = time.Unix(int64(updatedAtFloat), 0)

		apps = append(apps, &app)
	}

	return apps, nil
}

// GetRawSpec retrieves the raw specification for an application
func (s *PostgresStateStore) GetRawSpec(name string) (map[string]interface{}, error) {
	db, err := s.dbManager.GetConnection(false)
	if err != nil {
		return nil, fmt.Errorf("failed to get database connection: %w", err)
	}

	query := `SELECT raw_spec FROM apps WHERE name = $1`

	var rawSpecJSON []byte
	err = db.QueryRow(query, name).Scan(&rawSpecJSON)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("app not found: %s", name)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to query raw spec: %w", err)
	}

	var rawSpec map[string]interface{}
	if err := json.Unmarshal(rawSpecJSON, &rawSpec); err != nil {
		return nil, fmt.Errorf("failed to parse raw spec: %w", err)
	}

	return rawSpec, nil
}

// LogEvent logs a system event
func (s *PostgresStateStore) LogEvent(app, eventType string, data interface{}) error {
	db, err := s.dbManager.GetConnection(true)
	if err != nil {
		return fmt.Errorf("failed to get database connection: %w", err)
	}

	dataJSON, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal event data: %w", err)
	}

	query := `
		INSERT INTO events (app_name, event_type, message, timestamp, data)
		VALUES ($1, $2, $3, $4, $5)
	`

	message := fmt.Sprintf("%s: %s", app, eventType)
	timestamp := time.Now().Unix()

	_, err = db.Exec(query, app, eventType, message, timestamp, dataJSON)
	if err != nil {
		return fmt.Errorf("failed to log event: %w", err)
	}

	return nil
}

// LogScalingAction logs a scaling action
func (s *PostgresStateStore) LogScalingAction(
	app string,
	fromReplicas, toReplicas int,
	reason string,
	triggers []string,
	metrics *ScalingMetrics,
) error {
	db, err := s.dbManager.GetConnection(true)
	if err != nil {
		return fmt.Errorf("failed to get database connection: %w", err)
	}

	triggersJSON, err := json.Marshal(triggers)
	if err != nil {
		return fmt.Errorf("failed to marshal triggers: %w", err)
	}

	var metricsJSON []byte
	if metrics != nil {
		metricsJSON, err = json.Marshal(metrics)
		if err != nil {
			return fmt.Errorf("failed to marshal metrics: %w", err)
		}
	}

	query := `
		INSERT INTO scaling_actions 
		(app_name, from_replicas, to_replicas, reason, triggered_by, metrics, timestamp)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`

	timestamp := time.Now().Unix()

	_, err = db.Exec(query, app, fromReplicas, toReplicas, reason, triggersJSON, metricsJSON, timestamp)
	if err != nil {
		return fmt.Errorf("failed to log scaling action: %w", err)
	}

	return nil
}

// GetEvents retrieves recent events
func (s *PostgresStateStore) GetEvents(app string, limit int) ([]interface{}, error) {
	db, err := s.dbManager.GetConnection(false)
	if err != nil {
		return nil, fmt.Errorf("failed to get database connection: %w", err)
	}

	var query string
	var args []interface{}

	if app != "" {
		query = `
			SELECT id, app_name, event_type, message, timestamp, data
			FROM events
			WHERE app_name = $1
			ORDER BY timestamp DESC
			LIMIT $2
		`
		args = []interface{}{app, limit}
	} else {
		query = `
			SELECT id, app_name, event_type, message, timestamp, data
			FROM events
			ORDER BY timestamp DESC
			LIMIT $1
		`
		args = []interface{}{limit}
	}

	rows, err := db.Query(query, args...)
	if err != nil {
		return nil, fmt.Errorf("failed to query events: %w", err)
	}
	defer rows.Close()

	events := []interface{}{}
	for rows.Next() {
		var id int
		var appName, eventType, message string
		var timestamp int64
		var dataJSON []byte

		err := rows.Scan(&id, &appName, &eventType, &message, &timestamp, &dataJSON)
		if err != nil {
			return nil, fmt.Errorf("failed to scan event: %w", err)
		}

		var data map[string]interface{}
		if len(dataJSON) > 0 {
			json.Unmarshal(dataJSON, &data)
		}

		event := map[string]interface{}{
			"id":         id,
			"app_name":   appName,
			"event_type": eventType,
			"message":    message,
			"timestamp":  timestamp,
			"data":       data,
		}

		events = append(events, event)
	}

	return events, nil
}

// GetScalingHistory retrieves scaling history for an application
func (s *PostgresStateStore) GetScalingHistory(app string, limit int) ([]interface{}, error) {
	db, err := s.dbManager.GetConnection(false)
	if err != nil {
		return nil, fmt.Errorf("failed to get database connection: %w", err)
	}

	query := `
		SELECT id, app_name, from_replicas, to_replicas, reason, triggered_by, metrics, timestamp
		FROM scaling_actions
		WHERE app_name = $1
		ORDER BY timestamp DESC
		LIMIT $2
	`

	rows, err := db.Query(query, app, limit)
	if err != nil {
		return nil, fmt.Errorf("failed to query scaling history: %w", err)
	}
	defer rows.Close()

	history := []interface{}{}
	for rows.Next() {
		var id int
		var appName, reason string
		var fromReplicas, toReplicas int
		var timestamp int64
		var triggersJSON, metricsJSON []byte

		err := rows.Scan(&id, &appName, &fromReplicas, &toReplicas, &reason, &triggersJSON, &metricsJSON, &timestamp)
		if err != nil {
			return nil, fmt.Errorf("failed to scan scaling action: %w", err)
		}

		var triggers []string
		if len(triggersJSON) > 0 {
			json.Unmarshal(triggersJSON, &triggers)
		}

		var metrics map[string]interface{}
		if len(metricsJSON) > 0 {
			json.Unmarshal(metricsJSON, &metrics)
		}

		action := map[string]interface{}{
			"id":            id,
			"app_name":      appName,
			"from_replicas": fromReplicas,
			"to_replicas":   toReplicas,
			"reason":        reason,
			"triggered_by":  triggers,
			"metrics":       metrics,
			"timestamp":     timestamp,
		}

		history = append(history, action)
	}

	return history, nil
}
