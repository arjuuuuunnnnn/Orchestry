#!/bin/bash
set -e

# Setup replication slot on primary
echo "Setting up replication slot..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create replication slot if it doesn't exist
    SELECT pg_create_physical_replication_slot('replica_slot') 
    WHERE NOT EXISTS (
        SELECT 1 FROM pg_replication_slots WHERE slot_name = 'replica_slot'
    );
EOSQL

echo "Replication slot setup completed."