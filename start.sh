#!/bin/bash

set -e

echo "Starting AutoServe - Distributed Controller Cluster"
echo "===================================================="
echo "Enterprise-grade container orchestration with 3-node controller cluster and PostgreSQL HA"

if ! docker info > /dev/null 2>&1; then
    echo "Docker is not running. Please start Docker first."
    exit 1
fi

if [ ! -f "docker-compose.yml" ]; then
    echo "docker-compose.yml not found. Please run this script from the AutoServe directory."
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "Copying .env.example to .env..."
    cp .env.example .env
fi

if [ ! -f ".env.docker" ]; then
    echo "Copying .env.docker.example to .env.docker..."
    cp .env.docker.example .env.docker
fi

echo "Starting 3-node controller cluster with PostgreSQL HA..."
docker compose up --build -d

echo "Waiting for PostgreSQL primary and replica to be ready..."
sleep 15

echo "PostgreSQL High Availability cluster starting automatically..."
echo "Database containers will self-initialize with replication"

echo "Waiting for controller cluster to elect a leader..."
sleep 10

RETRIES=30
while [ $RETRIES -gt 0 ]; do
    if curl -s -f http://127.0.0.1:8000/cluster/health > /dev/null 2>&1; then
        leader_status=$(curl -s http://localhost:8000/cluster/leader 2>/dev/null | grep -o '"leader_id":"[^"]*"' | cut -d'"' -f4 || echo "")
        if [ -n "$leader_status" ]; then
            echo "AutoServe controller cluster is ready! Leader: $leader_status"
            break
        fi
    fi
    echo "   Waiting for controller cluster leader election... ($RETRIES retries left)"
    sleep 3
    RETRIES=$((RETRIES - 1))
done

if [ $RETRIES -eq 0 ]; then
    echo "AutoServe controller cluster failed to start. Check logs with: docker compose logs"
    exit 1
fi

echo ""
echo "AutoServe Distributed Controller Cluster is now running!"
echo "========================================================"
echo ""
echo "High Availability Services:"
docker compose ps

echo ""
echo "Controller Cluster Status:"
echo "  Load Balancer: http://127.0.0.1:8000 (API access)"
echo "  Controller 1:  http://127.0.0.1:8001"
echo "  Controller 2:  http://127.0.0.1:8002" 
echo "  Controller 3:  http://127.0.0.1:8003"
echo ""
echo "Database Cluster Status:"
echo "  Primary DB:  http://127.0.0.1:5432 (read/write)"
echo "  Replica DB:  http://127.0.0.1:5433 (read-only)"
echo ""
echo "Cluster Management:"
echo "   Cluster Status: curl http://127.0.0.1:8000/cluster/status"
echo "   Current Leader: curl http://127.0.0.1:8000/cluster/leader"
echo "   Health Check:   curl http://127.0.0.1:8000/cluster/health"
echo ""
echo "Next steps:"
echo "   1. Install CLI: pip install -e ."
echo "   2. Register an app: autoserve register test/my-server.yml"
echo "   3. Start the app: autoserve up my-server"
echo ""
echo "Production Endpoints:"
echo "   API Documentation: http://127.0.0.1:8000/docs"
echo "   Health Check: http://127.0.0.1:8000/health"
echo "   Database Status: Built-in PostgreSQL HA monitoring"
echo ""
echo "No single points of failure - PostgreSQL HA active"