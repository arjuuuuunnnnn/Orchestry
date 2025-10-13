package controller

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
	"text/template"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/client"
)

// NginxManagerImpl handles nginx configuration management and reloads.
type NginxManagerImpl struct {
	dockerClient  *client.Client
	containerName string
	confDir       string
	templatePath  string
	tmpl          *template.Template
}

// NewNginxManager creates a new manager from environment or params.
func NewNginxManager(containerName, confDir, templatePath string) (*NginxManagerImpl, error) {
	if containerName == "" {
		containerName = os.Getenv("ORCHESTRY_NGINX_CONTAINER")
	}
	if containerName == "" {
		return nil, fmt.Errorf("missing ORCHESTRY_NGINX_CONTAINER env var")
	}

	if confDir == "" {
		confDir = os.Getenv("ORCHESTRY_NGINX_CONF_DIR")
	}
	if confDir == "" {
		return nil, fmt.Errorf("missing ORCHESTRY_NGINX_CONF_DIR env var")
	}

	if templatePath == "" {
		templatePath = "configs/nginx_template_go.conf"
	}

	tmpl, err := template.ParseFiles(templatePath)
	if err != nil {
		return nil, fmt.Errorf("failed to load template: %w", err)
	}

	cli, err := client.NewClientWithOpts(client.FromEnv)
	if err != nil {
		return nil, fmt.Errorf("failed to create docker client: %w", err)
	}

	m := &NginxManagerImpl{
		dockerClient:  cli,
		containerName: containerName,
		confDir:       confDir,
		templatePath:  templatePath,
		tmpl:          tmpl,
	}

	if err := os.MkdirAll(confDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to ensure config dir: %w", err)
	}

	if err := m.ensureContainerRunning(); err != nil {
		return nil, err
	}

	log.Printf("NginxManager initialized for container %s", containerName)
	return m, nil
}

func (m *NginxManagerImpl) ensureContainerRunning() error {
	ctx := context.Background()
	container, err := m.dockerClient.ContainerInspect(ctx, m.containerName)
	if err != nil {
		return fmt.Errorf("nginx container %s not found: %w", m.containerName, err)
	}

	if !container.State.Running {
		log.Printf("Starting nginx container %s", m.containerName)
		if err := m.dockerClient.ContainerStart(ctx, m.containerName, types.ContainerStartOptions{}); err != nil {
			return fmt.Errorf("failed to start nginx container: %w", err)
		}
		log.Printf("Nginx container %s started", m.containerName)
	}
	return nil
}

func (m *NginxManagerImpl) validateAppName(name string) bool {
	if name == "" {
		return false
	}
	for _, r := range name {
		if !(r == '-' || r == '_' || (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9')) {
			return false
		}
	}
	return true
}

// UpdateUpstreams renders and applies an nginx config for an app.
func (m *NginxManagerImpl) UpdateUpstreams(app string, servers []Server) error {
	if !m.validateAppName(app) {
		return fmt.Errorf("invalid app name: %s", app)
	}
	if len(servers) == 0 {
		log.Printf("No servers provided for %s — removing config", app)
		return m.RemoveAppConfig(app)
	}

	confPath := filepath.Join(m.confDir, fmt.Sprintf("%s.conf", app))
	backupPath := confPath + ".backup"

	// Backup existing config
	if _, err := os.Stat(confPath); err == nil {
		if err := copyFile(confPath, backupPath); err != nil {
			return fmt.Errorf("failed to backup config: %w", err)
		}
	}

	// Convert servers to map format for template
	serverMaps := make([]map[string]interface{}, len(servers))
	for i, srv := range servers {
		serverMaps[i] = map[string]interface{}{
			"ip":   srv.IP,
			"port": srv.Port,
		}
	}

	// Render new config
	var buf bytes.Buffer
	err := m.tmpl.Execute(&buf, map[string]interface{}{
		"app":     app,
		"servers": serverMaps,
	})
	if err != nil {
		return fmt.Errorf("template render error: %w", err)
	}

	tmpFile := confPath + ".tmp"
	if err := os.WriteFile(tmpFile, buf.Bytes(), 0644); err != nil {
		return fmt.Errorf("failed to write temp config: %w", err)
	}
	os.Rename(tmpFile, confPath)

	// Test nginx config
	if !m.testConfig() {
		os.Remove(confPath)
		if _, err := os.Stat(backupPath); err == nil {
			os.Rename(backupPath, confPath)
		}
		return fmt.Errorf("nginx config test failed")
	}

	// Reload nginx
	if err := m.reloadNginx(); err != nil {
		os.Remove(confPath)
		if _, err := os.Stat(backupPath); err == nil {
			os.Rename(backupPath, confPath)
		}
		return fmt.Errorf("nginx reload failed: %w", err)
	}
	os.Remove(backupPath)
	log.Printf("Updated nginx config for %s", app)
	return nil
}

// RemoveAppConfig deletes the config file and reloads nginx.
func (m *NginxManagerImpl) RemoveAppConfig(app string) error {
	if !m.validateAppName(app) {
		return fmt.Errorf("invalid app name: %s", app)
	}
	confPath := filepath.Join(m.confDir, fmt.Sprintf("%s.conf", app))
	if err := os.Remove(confPath); err != nil && !os.IsNotExist(err) {
		return err
	}
	if !m.testConfig() {
		return fmt.Errorf("nginx config invalid after removal")
	}
	return m.reloadNginx()
}

// reloadNginx runs `nginx -s reload` in the container.
func (m *NginxManagerImpl) reloadNginx() error {
	return m.execInContainer([]string{"nginx", "-s", "reload"})
}

// testConfig runs `nginx -t` in the container.
func (m *NginxManagerImpl) testConfig() bool {
	err := m.execInContainer([]string{"nginx", "-t"})
	return err == nil
}

// execInContainer runs a command inside the nginx container.
func (m *NginxManagerImpl) execInContainer(cmd []string) error {
	ctx := context.Background()
	execID, err := m.dockerClient.ContainerExecCreate(ctx, m.containerName, types.ExecConfig{
		Cmd:          cmd,
		AttachStdout: true,
		AttachStderr: true,
	})
	if err != nil {
		return err
	}
	resp, err := m.dockerClient.ContainerExecAttach(ctx, execID.ID, types.ExecStartCheck{})
	if err != nil {
		return err
	}
	defer resp.Close()

	out, _ := io.ReadAll(resp.Reader)
	if !strings.Contains(string(out), "successful") && strings.Contains(strings.ToLower(string(out)), "error") {
		return fmt.Errorf("command failed: %s", string(out))
	}
	return nil
}

// GetNginxStatus fetches nginx status text and parses it.
func (m *NginxManagerImpl) GetNginxStatus() (map[string]interface{}, error) {
	ctx := context.Background()
	execID, err := m.dockerClient.ContainerExecCreate(ctx, m.containerName, types.ExecConfig{
		Cmd:          []string{"curl", "-s", "http://localhost:8080/nginx_status"},
		AttachStdout: true,
		AttachStderr: true,
	})
	if err != nil {
		return nil, err
	}
	resp, err := m.dockerClient.ContainerExecAttach(ctx, execID.ID, types.ExecStartCheck{})
	if err != nil {
		return nil, err
	}
	defer resp.Close()

	data, _ := io.ReadAll(resp.Reader)
	return parseNginxStatus(string(data))
}

// parseNginxStatus parses nginx stub_status text into metrics.
func parseNginxStatus(text string) (map[string]interface{}, error) {
	lines := strings.Split(strings.TrimSpace(text), "\n")
	if len(lines) < 4 {
		return nil, fmt.Errorf("unexpected nginx status output")
	}
	var active int
	fmt.Sscanf(lines[0], "Active connections: %d", &active)

	var accepts, handled, requests int
	fmt.Sscanf(lines[2], "%d %d %d", &accepts, &handled, &requests)

	var reading, writing, waiting int
	fmt.Sscanf(lines[3], "Reading: %d Writing: %d Waiting: %d", &reading, &writing, &waiting)

	return map[string]interface{}{
		"active_connections": active,
		"accepts":            accepts,
		"handled":            handled,
		"requests":           requests,
		"reading":            reading,
		"writing":            writing,
		"waiting":            waiting,
	}, nil
}

// GetContainerLogs returns nginx logs from Docker container.
func (m *NginxManagerImpl) GetContainerLogs(lines int) (string, error) {
	ctx := context.Background()
	opts := types.ContainerLogsOptions{
		ShowStdout: true,
		ShowStderr: true,
		Tail:       fmt.Sprint(lines),
		Timestamps: true,
	}
	rc, err := m.dockerClient.ContainerLogs(ctx, m.containerName, opts)
	if err != nil {
		return "", err
	}
	defer rc.Close()
	data, _ := io.ReadAll(rc)
	return string(data), nil
}

// RestartNginx restarts the nginx container.
func (m *NginxManagerImpl) RestartNginx() error {
	ctx := context.Background()
	timeout := 10
	return m.dockerClient.ContainerRestart(ctx, m.containerName, container.StopOptions{
		Timeout: &timeout,
	})
}

// Helper: copy file
func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}
