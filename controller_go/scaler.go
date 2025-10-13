package controller

import (
	"errors"
	"log"
	"math"
	"sort"
	"sync"
	"time"
)

const (
	MetricsRetentionMultiplier = 2
	MinScaleInStablePeriods    = 3
	EmergencyScaleFactor       = 10.0
)

type ScalingPolicy struct {
	MinReplicas          int
	MaxReplicas          int
	TargetRPSPerReplica  int
	MaxP95LatencyMs      int
	MaxConnPerReplica    int
	ScaleOutThresholdPct int
	ScaleInThresholdPct  int
	WindowSeconds        int
	CooldownSeconds      int
	MaxCPUPercent        float64
	MaxMemoryPercent     float64
}

func (p *ScalingPolicy) Validate() error {
	if p.MinReplicas < 1 {
		return errors.New("min_replicas must be >= 1")
	}
	if p.MaxReplicas < p.MinReplicas {
		return errors.New("max_replicas must be >= min_replicas")
	}
	if p.ScaleInThresholdPct >= p.ScaleOutThresholdPct {
		return errors.New("scale_in_threshold must be < scale_out_threshold")
	}
	if p.WindowSeconds < 1 {
		return errors.New("window_seconds must be >= 1")
	}
	if p.CooldownSeconds < 0 {
		return errors.New("cooldown_seconds must be >= 0")
	}
	return nil
}

type MetricPoint struct {
	Timestamp float64
	Value     float64
}

type ScalingMetrics struct {
	RPS               float64
	P95LatencyMs      float64
	ActiveConnections int
	CPUPercent        float64
	MemoryPercent     float64
	HealthyReplicas   int
	TotalReplicas     int
}

type ScalingDecision struct {
	ShouldScale     bool
	TargetReplicas  int
	CurrentReplicas int
	Reason          string
	TriggeredBy     []string
	Metrics         ScalingMetrics
}

type AutoScaler struct {
	mu                   sync.RWMutex
	policies             map[string]*ScalingPolicy
	metricsHistory       map[string]map[string][]MetricPoint
	lastScaleTime        map[string]float64
	scaleDecisions       map[string][]ScalingDecision
	lastScaleFactors     map[string]map[string]float64
	scaleInStablePeriods map[string]int
}

func NewAutoScaler() *AutoScaler {
	return &AutoScaler{
		policies:             make(map[string]*ScalingPolicy),
		metricsHistory:       make(map[string]map[string][]MetricPoint),
		lastScaleTime:        make(map[string]float64),
		scaleDecisions:       make(map[string][]ScalingDecision),
		lastScaleFactors:     make(map[string]map[string]float64),
		scaleInStablePeriods: make(map[string]int),
	}
}

func (a *AutoScaler) SetPolicy(app string, policy ScalingPolicy) error {
	if err := policy.Validate(); err != nil {
		return err
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	a.policies[app] = &policy
	log.Printf("[AutoScaler] Set policy for %s: min=%d max=%d out=%d%% in=%d%%",
		app, policy.MinReplicas, policy.MaxReplicas,
		policy.ScaleOutThresholdPct, policy.ScaleInThresholdPct)
	return nil
}

func (a *AutoScaler) AddMetrics(app string, metrics ScalingMetrics) {
	a.mu.Lock()
	defer a.mu.Unlock()

	ts := float64(time.Now().Unix())
	if _, ok := a.metricsHistory[app]; !ok {
		a.metricsHistory[app] = map[string][]MetricPoint{
			"rps":         {},
			"latency":     {},
			"connections": {},
			"cpu":         {},
			"memory":      {},
			"healthy":     {},
			"total":       {},
		}
	}

	h := a.metricsHistory[app]
	h["rps"] = append(h["rps"], MetricPoint{ts, metrics.RPS})
	h["latency"] = append(h["latency"], MetricPoint{ts, metrics.P95LatencyMs})
	h["connections"] = append(h["connections"], MetricPoint{ts, float64(metrics.ActiveConnections)})
	h["cpu"] = append(h["cpu"], MetricPoint{ts, metrics.CPUPercent})
	h["memory"] = append(h["memory"], MetricPoint{ts, metrics.MemoryPercent})
	h["healthy"] = append(h["healthy"], MetricPoint{ts, float64(metrics.HealthyReplicas)})
	h["total"] = append(h["total"], MetricPoint{ts, float64(metrics.TotalReplicas)})

	a.cleanOldMetrics(app, ts)
}

func (a *AutoScaler) cleanOldMetrics(app string, now float64) {
	policy, ok := a.policies[app]
	if !ok {
		return
	}
	cutoff := now - float64(policy.WindowSeconds*MetricsRetentionMultiplier)
	for metric, pts := range a.metricsHistory[app] {
		var kept []MetricPoint
		for _, p := range pts {
			if p.Timestamp >= cutoff {
				kept = append(kept, p)
			}
		}
		a.metricsHistory[app][metric] = kept
	}
}

func avg(vals []float64) float64 {
	if len(vals) == 0 {
		return 0
	}
	sum := 0.0
	for _, v := range vals {
		sum += v
	}
	return sum / float64(len(vals))
}

func percentile(vals []float64, p float64) float64 {
	if len(vals) == 0 {
		return 0
	}
	sort.Float64s(vals)
	k := int(float64(len(vals)-1) * p)
	return vals[k]
}

func (a *AutoScaler) getRecentMetrics(app string, window int) *ScalingMetrics {
	now := float64(time.Now().Unix())
	cutoff := now - float64(window)
	history, ok := a.metricsHistory[app]
	if !ok {
		return nil
	}

	filter := func(points []MetricPoint) []float64 {
		var vals []float64
		for _, p := range points {
			if p.Timestamp >= cutoff {
				vals = append(vals, p.Value)
			}
		}
		return vals
	}

	rpsVals := filter(history["rps"])
	latencyVals := filter(history["latency"])
	connVals := filter(history["connections"])
	cpuVals := filter(history["cpu"])
	memVals := filter(history["memory"])
	healthyVals := filter(history["healthy"])
	totalVals := filter(history["total"])

	if len(rpsVals) == 0 && len(latencyVals) == 0 {
		return nil
	}

	p95 := percentile(latencyVals, 0.95)
	return &ScalingMetrics{
		RPS:               avg(rpsVals),
		P95LatencyMs:      p95,
		ActiveConnections: int(avg(connVals)),
		CPUPercent:        avg(cpuVals),
		MemoryPercent:     avg(memVals),
		HealthyReplicas:   int(math.Max(1, avg(healthyVals))),
		TotalReplicas:     int(math.Max(1, avg(totalVals))),
	}
}

func (a *AutoScaler) Evaluate(app string, current int, mode string) ScalingDecision {
	a.mu.Lock()
	defer a.mu.Unlock()

	if mode == "manual" {
		return ScalingDecision{ShouldScale: false, TargetReplicas: current, CurrentReplicas: current, Reason: "Manual mode"}
	}

	policy, ok := a.policies[app]
	if !ok {
		return ScalingDecision{ShouldScale: false, TargetReplicas: current, CurrentReplicas: current, Reason: "No policy"}
	}

	if current < policy.MinReplicas {
		a.scaleInStablePeriods[app] = 0
		return ScalingDecision{
			ShouldScale:     true,
			TargetReplicas:  policy.MinReplicas,
			CurrentReplicas: current,
			Reason:          "Below min replicas",
			TriggeredBy:     []string{"min_replicas_enforcement"},
		}
	}

	last := a.lastScaleTime[app]
	if time.Since(time.Unix(int64(last), 0)) < time.Duration(policy.CooldownSeconds)*time.Second {
		return ScalingDecision{ShouldScale: false, TargetReplicas: current, CurrentReplicas: current, Reason: "In cooldown"}
	}

	metrics := a.getRecentMetrics(app, policy.WindowSeconds)
	if metrics == nil {
		return ScalingDecision{ShouldScale: false, TargetReplicas: current, CurrentReplicas: current, Reason: "No metrics"}
	}

	factors := a.calculateScaleFactors(*metrics, policy)
	a.lastScaleFactors[app] = factors

	decision := a.makeScalingDecision(app, current, factors, policy, *metrics)
	a.scaleDecisions[app] = append(a.scaleDecisions[app], decision)
	return decision
}

func (a *AutoScaler) calculateScaleFactors(metrics ScalingMetrics, policy *ScalingPolicy) map[string]float64 {
	factors := map[string]float64{}

	if metrics.HealthyReplicas == 0 {
		factors["no_healthy"] = EmergencyScaleFactor
		return factors
	}

	if policy.TargetRPSPerReplica > 0 {
		factors["rps"] = (metrics.RPS / float64(metrics.HealthyReplicas)) / float64(policy.TargetRPSPerReplica)
	}
	if policy.MaxP95LatencyMs > 0 && metrics.P95LatencyMs > 0 {
		factors["latency"] = metrics.P95LatencyMs / float64(policy.MaxP95LatencyMs)
	}
	if policy.MaxConnPerReplica > 0 {
		factors["connections"] = (float64(metrics.ActiveConnections) / float64(metrics.HealthyReplicas)) / float64(policy.MaxConnPerReplica)
	}
	if policy.MaxCPUPercent > 0 {
		factors["cpu"] = metrics.CPUPercent / policy.MaxCPUPercent
	}
	if policy.MaxMemoryPercent > 0 {
		factors["memory"] = metrics.MemoryPercent / policy.MaxMemoryPercent
	}
	return factors
}

func (a *AutoScaler) makeScalingDecision(app string, current int, factors map[string]float64, policy *ScalingPolicy, metrics ScalingMetrics) ScalingDecision {
	triggered := []string{}
	maxFactor := 0.0
	scaleOutThreshold := float64(policy.ScaleOutThresholdPct) / 100.0

	for k, f := range factors {
		if f > maxFactor {
			maxFactor = f
		}
		if f > scaleOutThreshold {
			triggered = append(triggered, k)
		}
	}

	target := current
	shouldScale := false
	reason := "Metrics within thresholds"

	if _, ok := factors["no_healthy"]; ok {
		target = int(math.Min(float64(current+1), float64(policy.MaxReplicas)))
		return ScalingDecision{ShouldScale: true, TargetReplicas: target, CurrentReplicas: current, Reason: "No healthy replicas", TriggeredBy: []string{"no_healthy"}, Metrics: metrics}
	}

	// Scale out
	if maxFactor > scaleOutThreshold && current < policy.MaxReplicas {
		desired := int(math.Ceil(float64(current) * maxFactor))
		if desired <= current {
			desired = current + 1
		}
		target = int(math.Min(float64(desired), float64(policy.MaxReplicas)))
		shouldScale = target > current
		reason = "Scale out triggered"
		a.scaleInStablePeriods[app] = 0
	}

	// Scale in
	if maxFactor < float64(policy.ScaleInThresholdPct)/100.0 && current > policy.MinReplicas {
		a.scaleInStablePeriods[app]++
		if a.scaleInStablePeriods[app] >= MinScaleInStablePeriods {
			target = int(math.Max(float64(current-1), float64(policy.MinReplicas)))
			shouldScale = target < current
			reason = "Scale in triggered"
			a.scaleInStablePeriods[app] = 0
		}
	}

	return ScalingDecision{ShouldScale: shouldScale, TargetReplicas: target, CurrentReplicas: current, Reason: reason, TriggeredBy: triggered, Metrics: metrics}
}

// EvaluateScaling is an alias for Evaluate for compatibility with API
func (a *AutoScaler) EvaluateScaling(app string, current int, mode string) ScalingDecision {
	return a.Evaluate(app, current, mode)
}

// RecordScalingAction records that a scaling action occurred
func (a *AutoScaler) RecordScalingAction(app string, replicas int) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.lastScaleTime[app] = float64(time.Now().Unix())
}

// GetMetricsSummary returns a summary of metrics for an app
func (a *AutoScaler) GetMetricsSummary(app string) map[string]interface{} {
	a.mu.RLock()
	defer a.mu.RUnlock()

	policy, ok := a.policies[app]
	if !ok {
		return map[string]interface{}{
			"error": "No policy set for app",
		}
	}

	metricsHistory, ok := a.metricsHistory[app]
	if !ok || len(metricsHistory) == 0 {
		return map[string]interface{}{
			"policy":         policy,
			"recent_metrics": nil,
			"window_seconds": policy.WindowSeconds,
		}
	}

	recentMetrics := a.getRecentMetrics(app, policy.WindowSeconds)

	return map[string]interface{}{
		"policy":          policy,
		"recent_metrics":  recentMetrics,
		"window_seconds":  policy.WindowSeconds,
		"last_scale_time": a.lastScaleTime[app],
	}
}

// GetLastScaleFactors returns the last calculated scale factors for an app
func (a *AutoScaler) GetLastScaleFactors(app string) map[string]float64 {
	a.mu.RLock()
	defer a.mu.RUnlock()

	if factors, ok := a.lastScaleFactors[app]; ok {
		return factors
	}
	return map[string]float64{}
}

// GetPolicy returns the scaling policy for an app
func (a *AutoScaler) GetPolicy(app string) *ScalingPolicy {
	a.mu.RLock()
	defer a.mu.RUnlock()

	return a.policies[app] // policies map already stores pointers, so return directly
}
