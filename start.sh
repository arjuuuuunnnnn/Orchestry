#!/bin/bash

set -e

echo "Starting AutoServe - Production PostgreSQL High Availability"
echo "============================================================"
echo "Enterprise-grade container orchestration with HA database"

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

echo "Starting PostgreSQL HA cluster and AutoServe services..."
docker-compose up --build -d

echo "Waiting for PostgreSQL primary and replica to be ready..."
sleep 15

echo "PostgreSQL High Availability cluster starting automatically..."
echo "Database containers will self-initialize with replication"

echo "Waiting for all services to be ready..."
sleep 5

RETRIES=30
while [ $RETRIES -gt 0 ]; do
    if curl -s -f http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "AutoServe controller is ready!"
        break
    fi
    echo "   Waiting for controller... ($RETRIES retries left)"
    sleep 2
    RETRIES=$((RETRIES - 1))
done

if [ $RETRIES -eq 0 ]; then
    echo "AutoServe controller failed to start. Check logs with: docker-compose logs"
    exit 1
fi

echo ""
echo "AutoServe PostgreSQL HA cluster is now running!"
echo "=================================================="
echo ""
echo "High Availability Services:"
docker-compose ps

echo ""
echo "Database Cluster Status:"
echo "  Primary DB:  http://127.0.0.1:5432 (read/write)"
echo "  Replica DB:  http://127.0.0.1:5433 (read-only)"
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