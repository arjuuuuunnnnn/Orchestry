package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"gopkg.in/yaml.v3"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"time"

	"cli_go/helpers"
	"github.com/spf13/cobra"
)

var orchestryURL string

func main() {
	rootCmd := &cobra.Command{
		Use:   "orchestry",
		Short: "Orchestry SDK CLI",
		PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
			if cmd.Name() == "config" {
				return nil
			}
			url, err := helpers.LoadConfig()
			if err != nil || url == "" {
				return fmt.Errorf("orchestry is not configured. Please run 'orchestry config' to set it up.")
			}
			orchestryURL = url
			return nil
		},
	}

	rootCmd.AddCommand(configCmd)
	rootCmd.AddCommand(registerCmd)
	rootCmd.AddCommand(upCmd)
	rootCmd.AddCommand(downCmd)
	rootCmd.AddCommand(statusCmd)
	rootCmd.AddCommand(scaleCmd)
	rootCmd.AddCommand(listCmd)
	rootCmd.AddCommand(metricsCmd)
	rootCmd.AddCommand(infoCmd)
	rootCmd.AddCommand(specCmd)
	rootCmd.AddCommand(logsCmd)

	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(1)
	}
}

//
// ─── COMMANDS ───────────────────────────────────────────────────────────────────
//

// CONFIG
var configCmd = &cobra.Command{
	Use:   "config",
	Short: "Configure orchestry by adding ORCHESTRY_HOST and ORCHESTRY_PORT",
	Run: func(cmd *cobra.Command, args []string) {
		fmt.Println("To configure orchestry, please enter the following details:")
		var host string
		var port int
		fmt.Print("Host (e.g., localhost or IP): ")
		fmt.Scanln(&host)
		fmt.Print("Port (e.g., 8000): ")
		fmt.Scanln(&port)

		apiURL := fmt.Sprintf("http://%s:%d", host, port)
		fmt.Printf("Connecting to orchestry at %s...\n", apiURL)

		if helpers.CheckServiceRunning(apiURL) {
			helpers.SaveConfig(host, port)
			fmt.Printf("Configuration saved to %s\n", helpers.ConfigFile)
		} else {
			fmt.Fprintln(os.Stderr, "Failed to connect to the specified host and port. Please ensure the orchestry controller is running.")
			os.Exit(1)
		}
	},
}

// REGISTER
var registerCmd = &cobra.Command{
	Use:   "register [config]",
	Short: "Register an app from YAML/JSON spec",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		configFile := args[0]
		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running. Run 'orchestry config' to configure.")
			os.Exit(1)
		}

		if _, err := os.Stat(configFile); os.IsNotExist(err) {
			fmt.Fprintf(os.Stderr, "Config file '%s' not found\n", configFile)
			os.Exit(1)
		}

		data, err := os.ReadFile(configFile)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error reading file:", err)
			os.Exit(1)
		}

		var spec interface{}
		if filepath.Ext(configFile) == ".yaml" || filepath.Ext(configFile) == ".yml" {
			if err := yaml.Unmarshal(data, &spec); err != nil {
				fmt.Fprintln(os.Stderr, "YAML error:", err)
				os.Exit(1)
			}
		} else {
			if err := json.Unmarshal(data, &spec); err != nil {
				fmt.Fprintln(os.Stderr, "JSON error:", err)
				os.Exit(1)
			}
		}

		body, _ := json.Marshal(spec)
		resp, err := http.Post(fmt.Sprintf("%s/apps/register", orchestryURL), "application/json", bytes.NewBuffer(body))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()

		printResponse(resp, "App registered successfully!", "Registration failed")
	},
}

// UP
var upCmd = &cobra.Command{
	Use:   "up [name]",
	Short: "Start the app",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		name := args[0]
		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}
		resp, err := http.Post(fmt.Sprintf("%s/apps/%s/up", orchestryURL, name), "application/json", nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()
		printResponse(resp, "", "")
	},
}

// DOWN
var downCmd = &cobra.Command{
	Use:   "down [name]",
	Short: "Stop the app",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		name := args[0]
		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}
		resp, err := http.Post(fmt.Sprintf("%s/apps/%s/down", orchestryURL, name), "application/json", nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()
		printResponse(resp, "", "")
	},
}

// STATUS
var statusCmd = &cobra.Command{
	Use:   "status [name]",
	Short: "Check app status",
	Args:  cobra.ExactArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		name := args[0]
		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}
		resp, err := http.Get(fmt.Sprintf("%s/apps/%s/status", orchestryURL, name))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()
		printResponse(resp, "", "")
	},
}

// SCALE
var scaleCmd = &cobra.Command{
	Use:   "scale [name] [replicas]",
	Short: "Scale app to specific replica count",
	Args:  cobra.ExactArgs(2),
	Run: func(cmd *cobra.Command, args []string) {
		name := args[0]
		var replicas int
		fmt.Sscanf(args[1], "%d", &replicas)

		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}

		infoResp, err := http.Get(fmt.Sprintf("%s/apps/%s/status", orchestryURL, name))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer infoResp.Body.Close()

		if infoResp.StatusCode == 404 {
			fmt.Fprintf(os.Stderr, "App '%s' not found\n", name)
			os.Exit(1)
		}

		var appInfo map[string]interface{}
		json.NewDecoder(infoResp.Body).Decode(&appInfo)
		mode := "auto"
		if m, ok := appInfo["mode"].(string); ok {
			mode = m
		}

		fmt.Printf("Scaling '%s' to %d replicas (%s mode)\n", name, replicas, mode)
		body, _ := json.Marshal(map[string]int{"replicas": replicas})
		resp, err := http.Post(fmt.Sprintf("%s/apps/%s/scale", orchestryURL, name), "application/json", bytes.NewBuffer(body))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()
		printResponse(resp, "", "")
	},
}

// LIST
var listCmd = &cobra.Command{
	Use:   "list",
	Short: "List all applications",
	Run: func(cmd *cobra.Command, args []string) {
		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}
		resp, err := http.Get(fmt.Sprintf("%s/apps", orchestryURL))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()
		printResponse(resp, "", "")
	},
}

// METRICS
var metricsCmd = &cobra.Command{
	Use:   "metrics [name]",
	Short: "Get system or app metrics",
	Args:  cobra.MaximumNArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}
		url := fmt.Sprintf("%s/metrics", orchestryURL)
		if len(args) > 0 {
			url = fmt.Sprintf("%s/apps/%s/metrics", orchestryURL, args[0])
		}
		resp, err := http.Get(url)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()
		printResponse(resp, "", "")
	},
}

// INFO
var infoCmd = &cobra.Command{
	Use:   "info",
	Short: "Show orchestry system information and status",
	Run: func(cmd *cobra.Command, args []string) {
		client := http.Client{Timeout: 5 * time.Second}
		resp, err := client.Get(fmt.Sprintf("%s/health", orchestryURL))
		if err != nil {
			fmt.Println("orchestry Controller: Not running")
			fmt.Println("To start: docker-compose up -d")
			return
		}
		defer resp.Body.Close()

		if resp.StatusCode == 200 {
			fmt.Println("orchestry Controller: Running")
			fmt.Println("API:", orchestryURL)
			appsResp, _ := http.Get(fmt.Sprintf("%s/apps", orchestryURL))
			defer appsResp.Body.Close()
			var apps []interface{}
			json.NewDecoder(appsResp.Body).Decode(&apps)
			fmt.Printf("Apps: %d registered\n", len(apps))
			fmt.Println("\nDocker Services:")
			out, _ := exec.Command("docker-compose", "ps", "--format", "table").CombinedOutput()
			fmt.Println(string(out))
		} else {
			fmt.Println("orchestry Controller: Not healthy")
		}
	},
}

// SPEC
var specCmd = &cobra.Command{
	Use:   "spec [name]",
	Short: "Get app specification",
	Run: func(cmd *cobra.Command, args []string) {
		name := args[0]
		raw, _ := cmd.Flags().GetBool("raw")

		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}

		resp, err := http.Get(fmt.Sprintf("%s/apps/%s/raw", orchestryURL, name))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()

		if resp.StatusCode == 404 {
			fmt.Fprintf(os.Stderr, "App '%s' not found\n", name)
			os.Exit(1)
		}

		var data map[string]interface{}
		json.NewDecoder(resp.Body).Decode(&data)

		if raw {
			if rawSpec, ok := data["raw"]; ok {
				yamlData, _ := yaml.Marshal(rawSpec)
				fmt.Println(string(yamlData))
			} else {
				fmt.Println("No raw spec available")
			}
		} else {
			parsed := data["parsed"].(map[string]interface{})
			delete(parsed, "created_at")
			delete(parsed, "updated_at")
			yamlData, _ := yaml.Marshal(parsed)
			fmt.Println(string(yamlData))
		}
	},
}

// LOGS
var logsCmd = &cobra.Command{
	Use:   "logs [name]",
	Short: "Get logs for an application",
	Run: func(cmd *cobra.Command, args []string) {
		name := args[0]
		lines, _ := cmd.Flags().GetInt("lines")
		follow, _ := cmd.Flags().GetBool("follow")

		if !helpers.CheckServiceRunning(orchestryURL) {
			fmt.Fprintln(os.Stderr, "orchestry controller is not running.")
			os.Exit(1)
		}

		url := fmt.Sprintf("%s/apps/%s/logs?lines=%d", orchestryURL, name, lines)
		resp, err := http.Get(url)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Error:", err)
			os.Exit(1)
		}
		defer resp.Body.Close()

		var data map[string]interface{}
		json.NewDecoder(resp.Body).Decode(&data)
		logsList := data["logs"].([]interface{})
		total := int(data["total_containers"].(float64))

		fmt.Printf("Logs for '%s' (%d container(s)):\n\n", name, total)

		// Sort and print logs
		sort.Slice(logsList, func(i, j int) bool {
			a := logsList[i].(map[string]interface{})["timestamp"].(float64)
			b := logsList[j].(map[string]interface{})["timestamp"].(float64)
			return a < b
		})

		for _, l := range logsList {
			entry := l.(map[string]interface{})
			ts := time.Unix(int64(entry["timestamp"].(float64)), 0)
			fmt.Printf("%s [%s] %s\n", ts.Format("2006-01-02 15:04:05"), entry["container"], entry["message"])
		}

		if follow {
			fmt.Println("\nNote: Log following (--follow/-f) not implemented yet.")
		}
	},
}

func init() {
	specCmd.Flags().Bool("raw", false, "Show raw spec")
	logsCmd.Flags().IntP("lines", "n", 100, "Number of log lines")
	logsCmd.Flags().BoolP("follow", "f", false, "Follow log output")
}

// HELPERS
func printResponse(resp *http.Response, successMsg, failMsg string) {
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode == 200 {
		if successMsg != "" {
			fmt.Println(successMsg)
		}
		var out interface{}
		json.Unmarshal(body, &out)
		pretty, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(pretty))
	} else {
		if failMsg != "" {
			fmt.Fprintln(os.Stderr, failMsg)
		}
		fmt.Fprintln(os.Stderr, string(body))
	}
}
