package helpers

import (
	"errors"
	"fmt"
	"gopkg.in/yaml.v3"
	"io/ioutil"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

type Config struct {
	Host string `yaml:"host"`
	Port int   `yaml:"port"`
}

var (
	appName = "orchestry"
	ConfigFile string
)

func init() {
	dir, err := os.UserConfigDir()
	if err != nil {
		fmt.Println("Error getting config directory:", err)
		os.Exit(1)
	}
	configDir := filepath.Join(dir, appName)
	ConfigFile = filepath.Join(configDir, "config.yaml")
}

func SaveConfig(host string, port int) error {
	dir := filepath.Dir(ConfigFile)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	
	data := Config{Host: host, Port: port}
	out, err := yaml.Marshal(&data)
	if err != nil {
		return err
	}
	return ioutil.WriteFile(ConfigFile, out, 0644)
}

func LoadConfig() (string, error) {
	if _, err := os.Stat(ConfigFile); os.IsNotExist(err) {
		return "", errors.New("config file not found")
	}
	data, err := ioutil.ReadFile(ConfigFile)
	if err != nil {
		return "", err
	}
	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return "", err
	}
	if cfg.Host == "" || cfg.Port == 0 {
		return "", errors.New("Invalid Config")
	}
	return fmt.Sprintf("http://%s:%d", cfg.Host, cfg.Port), nil
}

func CheckServiceRunning(apiURL string) bool {
	if apiURL == "" {
		fmt.Fprintln(os.Stderr, "orchestry is not configured")
		fmt.Fprintln(os.Stderr, "Please run 'orchestry config' to set it up.")
		os.Exit(1)
	}
	client := http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get(apiURL + "/health")
	if err != nil {
		fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "Please ensure you are running orchestry")
		fmt.Fprintln(os.Stderr, "To start orchesrty:")
		fmt.Fprintln(os.Stderr, "docker-compose up -d")
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "Or use the quick start script:")
		fmt.Fprintln(os.Stderr, "./start.sh")
		fmt.Fprintln(os.Stderr, "")
		os.Exit(1)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusOK {
		return true
	}
	fmt.Println(os.Stderr, "Error: orchestry returned status %d\n", resp.StatusCode)
	return false
}

