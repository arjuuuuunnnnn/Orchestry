#!/bin/bash
set -e

# Function to run commands as postgres user
run_as_postgres() {
    su - postgres -c "$1"
}

# Wait for primary to be ready
echo "Waiting for primary database to be ready..."
until pg_isready -h postgres-primary -p 5432 -U autoserve; do
    echo "Primary database is not ready yet. Sleeping..."
    sleep 2
done

echo "Primary database is ready. Setting up replica..."

# Check if this is the first run by looking for a marker file
REPLICA_SETUP_MARKER="/var/lib/postgresql/replica_initialized"

if [ -f "$REPLICA_SETUP_MARKER" ]; then
    echo "Replica already initialized. Starting PostgreSQL..."
    exec docker-entrypoint.sh postgres
fi

# Ensure postgres user owns PGDATA
chown -R postgres:postgres "$PGDATA"

# Initialize empty database if needed
if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "Initializing empty database..."
    run_as_postgres "initdb -D $PGDATA"
fi

# Stop PostgreSQL if running
run_as_postgres "pg_ctl -D $PGDATA -m fast -w stop" || true

# Clean the data directory but preserve structure
echo "Cleaning data directory..."
run_as_postgres "rm -rf $PGDATA/*"

# Create base backup from primary
echo "Creating base backup from primary..."
export PGPASSWORD=replication_password
run_as_postgres "PGPASSWORD=replication_password pg_basebackup -h postgres-primary -D $PGDATA -U replication_user -v -P -R"

# Create standby.signal for PostgreSQL 12+
run_as_postgres "touch $PGDATA/standby.signal"

# Create postgresql.conf for replica
cat > "$PGDATA/postgresql.conf" << EOF
# Basic settings
listen_addresses = '*'
port = 5432
max_connections = 100
shared_buffers = 128MB

# Replication settings
hot_standby = on
max_wal_senders = 3
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /var/lib/postgresql/archive/%f && cp %p /var/lib/postgresql/archive/%f'

# Replica-specific settings
primary_conninfo = 'host=postgres-primary port=5432 user=replication_user password=replication_password application_name=replica'
primary_slot_name = 'replica_slot'
hot_standby_feedback = on
EOF

# Create pg_hba.conf for replica
cat > "$PGDATA/pg_hba.conf" << EOF
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
host    all             all             0.0.0.0/0               md5
host    replication     replication_user 0.0.0.0/0              md5
EOF

# Set proper permissions
chown -R postgres:postgres "$PGDATA"
chmod 700 "$PGDATA"

# Mark replica as initialized
touch "$REPLICA_SETUP_MARKER"

echo "Replica setup completed. Starting PostgreSQL..."
exec docker-entrypoint.sh postgres