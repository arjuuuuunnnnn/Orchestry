#!/bin/bash

# AutoServe Cluster Startup Script
# Starts the 3-node controller cluster with leader election
# Note: You can also just use: docker compose up --build -d

set -e

echo "Starting AutoServe Distributed Controller Cluster..."
echo "=================================================="
echo "Alternatively, you can just run: docker compose up --build -d"
echo ""

# Check if Docker and Docker Compose are available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed or not in PATH"
    exit 1
fi

# Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p logs
mkdir -p configs/nginx

# Start the entire cluster
echo "� Starting AutoServe with clustered controllers..."
docker compose up --build -d

# Wait for cluster to be ready
echo "⏳ Waiting for cluster to elect a leader..."

max_attempts=20
attempt=0

while [ $attempt -lt $max_attempts ]; do
    if curl -s http://localhost:8000/cluster/health >/dev/null 2>&1; then
        leader_status=$(curl -s http://localhost:8000/cluster/leader 2>/dev/null | grep -o '"leader_id":"[^"]*"' | cut -d'"' -f4 || echo "")
        if [ -n "$leader_status" ]; then
            echo "✅ Cluster is ready! Leader elected: $leader_status"
            break
        fi
    fi
    
    attempt=$((attempt + 1))
    echo "⏳ Waiting for leader election... (attempt $attempt/$max_attempts)"
    sleep 3
done

if [ $attempt -eq $max_attempts ]; then
    echo "⚠️  Cluster started but leader election may still be in progress"
    echo "Check cluster status with: curl http://localhost:8000/cluster/status"
fi

echo ""
echo "🎉 AutoServe Distributed Controller Cluster is now running!"
echo "=================================================="
echo ""
echo "🌐 Controller API Load Balancer: http://localhost:8000"
echo "📊 Individual Controller Nodes:"
echo "   • Controller 1: http://localhost:8001"
echo "   • Controller 2: http://localhost:8002"
echo "   • Controller 3: http://localhost:8003"
echo ""
echo "🔍 Cluster Status Commands:"
echo "   • curl http://localhost:8000/cluster/status"
echo "   • curl http://localhost:8000/cluster/leader"
echo "   • curl http://localhost:8000/cluster/health"
echo ""
echo "📋 Database Cluster Status:"
docker compose exec postgres-primary psql -U autoserve -d autoserve -c "SELECT application_name, state, sync_state FROM pg_stat_replication;"

echo ""
echo "🔧 Container Status:"  
docker compose ps

echo ""
echo "📊 Cluster Health Check:"
sleep 2
curl -s http://localhost:8000/cluster-health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "Cluster health check endpoint not ready yet"

echo ""
echo "🏁 Cluster startup complete!"
echo ""
echo "💡 To monitor logs: docker compose logs -f"
echo "💡 To stop cluster: docker compose down"
