package statego

import "time"

// AppRecord represents an application record in the database
type AppRecord struct {
	Name         string                 `json:"name"`
	Spec         map[string]interface{} `json:"spec"`
	Status       string                 `json:"status"`
	CreatedAt    float64                `json:"created_at"`
	UpdatedAt    float64                `json:"updated_at"`
	Replicas     int                    `json:"replicas"`
	LastScaledAt *float64               `json:"last_scaled_at,omitempty"`
	Mode         string                 `json:"mode"`
}

// InstanceRecord represents a container instance record
type InstanceRecord struct {
	ContainerID     string   `json:"container_id"`
	AppName         string   `json:"app_name"`
	IP              string   `json:"ip"`
	Port            int      `json:"port"`
	Status          string   `json:"status"`
	CreatedAt       float64  `json:"created_at"`
	UpdatedAt       float64  `json:"updated_at"`
	FailureCount    int      `json:"failure_count"`
	LastHealthCheck *float64 `json:"last_health_check,omitempty"`
}

// EventRecord represents a system event record
type EventRecord struct {
	ID        int                    `json:"id"`
	AppName   string                 `json:"app_name"`
	EventType string                 `json:"event_type"`
	Message   string                 `json:"message"`
	Timestamp float64                `json:"timestamp"`
	Details   map[string]interface{} `json:"details,omitempty"`
}

// ScalingEvent represents a scaling history record
type ScalingEvent struct {
	ID              int                    `json:"id"`
	AppName         string                 `json:"app_name"`
	FromReplicas    int                    `json:"from_replicas"`
	ToReplicas      int                    `json:"to_replicas"`
	TriggerReason   string                 `json:"trigger_reason"`
	MetricsSnapshot map[string]interface{} `json:"metrics_snapshot,omitempty"`
	Timestamp       float64                `json:"timestamp"`
}

// TimeNow returns current time as Unix timestamp with millisecond precision
func TimeNow() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}

// TimeToFloat64 converts time.Time to Unix timestamp
func TimeToFloat64(t time.Time) float64 {
	return float64(t.UnixNano()) / 1e9
}

// Float64ToTime converts Unix timestamp to time.Time
func Float64ToTime(f float64) time.Time {
	sec := int64(f)
	nsec := int64((f - float64(sec)) * 1e9)
	return time.Unix(sec, nsec)
}
