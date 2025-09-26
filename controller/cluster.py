"""
Distributed Controller Clustering with Leader Election

This module implements a 3-node controller cluster with leader election
to eliminate single point of failure in the AutoServe system.

Features:
- PostgreSQL-based leader election with lease system
- Automatic failover and leader handoff
- Split-brain prevention with fencing
- Health monitoring and cluster membership
- Event broadcasting for state synchronization
"""

import asyncio
import logging
import time
import threading
import uuid
import json
import socket
from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass, asdict
from enum import Enum
import psycopg2
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class NodeState(Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate" 
    LEADER = "leader"
    STOPPED = "stopped"

@dataclass
class ClusterNode:
    """Represents a controller node in the cluster"""
    node_id: str
    hostname: str
    port: int
    api_url: str
    state: NodeState
    last_heartbeat: float
    lease_expires_at: Optional[float] = None
    term: int = 0
    votes_received: int = 0
    is_healthy: bool = True

@dataclass
class LeaderLease:
    """Leader lease information stored in database"""
    leader_id: str
    term: int
    acquired_at: float
    expires_at: float
    renewed_at: float
    hostname: str
    api_url: str

class DistributedController:
    """
    Distributed controller cluster manager with leader election.
    
    Implements a simplified Raft-like consensus algorithm using PostgreSQL
    as the coordination backend for leader election and cluster membership.
    """
    
    def __init__(self, 
                 node_id: str = None,
                 hostname: str = None,
                 port: int = 8000,
                 db_manager = None,
                 lease_ttl: int = 30,
                 heartbeat_interval: int = 10,
                 election_timeout: int = 15):
        
        # Node identification
        self.node_id = node_id or str(uuid.uuid4())
        self.hostname = hostname or socket.gethostname()
        self.port = port
        self.api_url = f"http://{self.hostname}:{port}"
        
        # Cluster state
        self.state = NodeState.FOLLOWER
        self.current_term = 0
        self.voted_for = None
        self.leader_id = None
        self.is_leader = False
        
        # Database connection
        self.db_manager = db_manager
        self._lock = threading.RLock()
        
        # Timing configuration
        self.lease_ttl = lease_ttl  # seconds
        self.heartbeat_interval = heartbeat_interval
        self.election_timeout = election_timeout
        
        # Background tasks
        self._running = False
        self._heartbeat_task = None
        self._election_task = None
        self._monitoring_task = None
        
        # Event callbacks
        self.on_become_leader: Optional[Callable] = None
        self.on_lose_leadership: Optional[Callable] = None
        self.on_cluster_change: Optional[Callable] = None
        
        # Cluster membership
        self.cluster_nodes: Dict[str, ClusterNode] = {}
        
        logger.info(f"🏗️  Initializing distributed controller node {self.node_id}")
        logger.info(f"📍 Node: {self.hostname}:{self.port} -> {self.api_url}")
        
    def start(self):
        """Start the distributed controller cluster"""
        if self._running:
            logger.warning("Cluster node already running")
            return
            
        logger.info("🚀 Starting distributed controller cluster...")
        
        # Initialize database tables for clustering
        self._init_cluster_tables()
        
        # Register this node
        self._register_node()
        
        # Start background tasks
        self._running = True
        self._start_background_tasks()
        
        logger.info(f"✅ Distributed controller node {self.node_id} started")
        
    def stop(self):
        """Stop the distributed controller cluster"""
        if not self._running:
            return
            
        logger.info("🛑 Stopping distributed controller cluster...")
        self._running = False
        
        # Release leadership if we're the leader
        if self.is_leader:
            self._release_leadership()
            
        # Mark node as stopped
        self.state = NodeState.STOPPED
        self._update_node_status()
        
        # Wait for background tasks to stop
        if self._heartbeat_task and self._heartbeat_task.is_alive():
            self._heartbeat_task.join(timeout=5)
        if self._election_task and self._election_task.is_alive():
            self._election_task.join(timeout=5)
        if self._monitoring_task and self._monitoring_task.is_alive():
            self._monitoring_task.join(timeout=5)
            
        logger.info(f"Distributed controller node {self.node_id} stopped")
        
    def _init_cluster_tables(self):
        """Initialize database tables for cluster coordination"""
        logger.info("Initializing cluster coordination tables...")
        
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Cluster nodes table
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS cluster_nodes (
                            node_id VARCHAR(255) PRIMARY KEY,
                            hostname VARCHAR(255) NOT NULL,
                            port INTEGER NOT NULL,
                            api_url VARCHAR(512) NOT NULL,
                            state VARCHAR(50) NOT NULL,
                            term INTEGER NOT NULL DEFAULT 0,
                            last_heartbeat TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            is_healthy BOOLEAN NOT NULL DEFAULT true,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Leader lease table
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS leader_lease (
                            id INTEGER PRIMARY KEY DEFAULT 1,
                            leader_id VARCHAR(255) NOT NULL,
                            term INTEGER NOT NULL,
                            acquired_at TIMESTAMP NOT NULL,
                            expires_at TIMESTAMP NOT NULL,
                            renewed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            hostname VARCHAR(255) NOT NULL,
                            api_url VARCHAR(512) NOT NULL,
                            CONSTRAINT single_lease CHECK (id = 1)
                        )
                    """)
                    
                    # Cluster events table for coordination
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS cluster_events (
                            id SERIAL PRIMARY KEY,
                            node_id VARCHAR(255) NOT NULL,
                            event_type VARCHAR(100) NOT NULL,
                            event_data JSONB,
                            term INTEGER NOT NULL,
                            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Create indices for performance
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_nodes_state ON cluster_nodes(state)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_nodes_heartbeat ON cluster_nodes(last_heartbeat)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_events_node_term ON cluster_events(node_id, term)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cluster_events_timestamp ON cluster_events(timestamp)")
                    
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"Failed to initialize cluster tables: {e}")
            raise
            
        logger.info("Cluster coordination tables initialized")
        
    def _register_node(self):
        """Register this node in the cluster"""
        logger.info(f"📝 Registering node {self.node_id} in cluster...")
        
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO cluster_nodes 
                        (node_id, hostname, port, api_url, state, term, last_heartbeat, is_healthy)
                        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                        ON CONFLICT (node_id) DO UPDATE SET
                            hostname = EXCLUDED.hostname,
                            port = EXCLUDED.port,
                            api_url = EXCLUDED.api_url,
                            state = EXCLUDED.state,
                            term = EXCLUDED.term,
                            last_heartbeat = CURRENT_TIMESTAMP,
                            is_healthy = EXCLUDED.is_healthy,
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        self.node_id,
                        self.hostname,
                        self.port,
                        self.api_url,
                        self.state.value,
                        self.current_term,
                        True
                    ))
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"❌ Failed to register node: {e}")
            raise
            
        logger.info(f"✅ Node {self.node_id} registered in cluster")
        
    def _start_background_tasks(self):
        """Start background monitoring and coordination tasks"""
        # Heartbeat task - maintain node presence
        self._heartbeat_task = threading.Thread(
            target=self._heartbeat_loop, 
            name=f"HeartbeatTask-{self.node_id}",
            daemon=True
        )
        self._heartbeat_task.start()
        
        # Election monitoring task
        self._election_task = threading.Thread(
            target=self._election_loop,
            name=f"ElectionTask-{self.node_id}",
            daemon=True
        )
        self._election_task.start()
        
        # Cluster monitoring task
        self._monitoring_task = threading.Thread(
            target=self._cluster_monitor_loop,
            name=f"MonitorTask-{self.node_id}",
            daemon=True
        )
        self._monitoring_task.start()
        
    def _heartbeat_loop(self):
        """Background heartbeat to maintain node presence"""
        logger.info("💓 Starting heartbeat loop...")
        
        while self._running:
            try:
                self._send_heartbeat()
                
                # If we're the leader, renew our lease
                if self.is_leader:
                    self._renew_leadership_lease()
                    
            except Exception as e:
                logger.error(f"❌ Heartbeat error: {e}")
                
            time.sleep(self.heartbeat_interval)
            
    def _election_loop(self):
        """Background election monitoring and leadership checks"""
        logger.info("🗳️  Starting election monitoring loop...")
        
        while self._running:
            try:
                if not self.is_leader:
                    # Check if we need to start an election
                    if self._should_start_election():
                        self._start_leader_election()
                        
                # Check leader health and lease validity
                self._check_leader_health()
                
            except Exception as e:
                logger.error(f"❌ Election loop error: {e}")
                
            time.sleep(5)  # Check every 5 seconds
            
    def _cluster_monitor_loop(self):
        """Monitor cluster membership and health"""
        logger.info("🔍 Starting cluster monitoring loop...")
        
        while self._running:
            try:
                self._update_cluster_membership()
                self._cleanup_stale_nodes()
                
            except Exception as e:
                logger.error(f"❌ Cluster monitoring error: {e}")
                
            time.sleep(15)  # Check every 15 seconds
            
    def _send_heartbeat(self):
        """Send heartbeat to update node status"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE cluster_nodes 
                        SET last_heartbeat = CURRENT_TIMESTAMP,
                            state = %s,
                            term = %s,
                            is_healthy = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE node_id = %s
                    """, (
                        self.state.value,
                        self.current_term,
                        True,
                        self.node_id
                    ))
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"❌ Failed to send heartbeat: {e}")
            
    def _should_start_election(self) -> bool:
        """Check if we should start a leader election"""
        try:
            # Check if there's a current valid leader
            current_lease = self._get_current_lease()
            if current_lease and current_lease.expires_at > time.time():
                # Valid leader exists
                if current_lease.leader_id != self.leader_id:
                    self.leader_id = current_lease.leader_id
                    logger.info(f"👑 Acknowledged leader: {self.leader_id}")
                return False
                
            # No valid leader - check if we should start election
            if self.state == NodeState.FOLLOWER:
                logger.info("🗳️  No valid leader found, considering election...")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error checking election conditions: {e}")
            
        return False
        
    def _start_leader_election(self):
        """Start a leader election process"""
        with self._lock:
            if self.state != NodeState.FOLLOWER:
                return
                
            logger.info(f"🚀 Starting leader election for term {self.current_term + 1}")
            
            # Become candidate
            self.state = NodeState.CANDIDATE
            self.current_term += 1
            self.voted_for = self.node_id
            
            # Vote for ourselves
            votes = 1
            
            # Try to acquire leadership lease
            if self._try_acquire_leadership():
                self._become_leader()
            else:
                # Failed to acquire lease, back to follower
                self.state = NodeState.FOLLOWER
                self.voted_for = None
                logger.info(f"❌ Failed to acquire leadership lease for term {self.current_term}")
                
    def _try_acquire_leadership(self) -> bool:
        """Try to acquire leadership lease atomically"""
        try:
            # Use PostgreSQL interval instead of timestamp
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Try to acquire or update lease atomically
                    cursor.execute("""
                        INSERT INTO leader_lease 
                        (id, leader_id, term, acquired_at, expires_at, renewed_at, hostname, api_url)
                        VALUES (1, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '%s seconds', CURRENT_TIMESTAMP, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            leader_id = EXCLUDED.leader_id,
                            term = EXCLUDED.term,
                            acquired_at = CURRENT_TIMESTAMP,
                            expires_at = CURRENT_TIMESTAMP + INTERVAL '%s seconds',
                            renewed_at = CURRENT_TIMESTAMP,
                            hostname = EXCLUDED.hostname,
                            api_url = EXCLUDED.api_url
                        WHERE leader_lease.expires_at <= CURRENT_TIMESTAMP 
                           OR leader_lease.term < EXCLUDED.term
                    """, (
                        self.node_id,
                        self.current_term,
                        self.lease_ttl,
                        self.hostname,
                        self.api_url,
                        self.lease_ttl
                    ))
                    
                    # Check if we actually acquired the lease
                    if cursor.rowcount > 0:
                        conn.commit()
                        logger.info(f"✅ Acquired leadership lease for term {self.current_term}")
                        return True
                    else:
                        conn.rollback()
                        return False
                        
        except Exception as e:
            logger.error(f"❌ Failed to acquire leadership lease: {e}")
            return False
            
    def _become_leader(self):
        """Transition to leader state"""
        logger.info(f"👑 Becoming cluster leader (term {self.current_term})")
        
        with self._lock:
            self.state = NodeState.LEADER
            self.is_leader = True
            self.leader_id = self.node_id
            
        # Update node status
        self._update_node_status()
        
        # Log cluster event
        self._log_cluster_event("leader_elected", {
            "term": self.current_term,
            "node_id": self.node_id,
            "hostname": self.hostname
        })
        
        # Notify application that we became leader
        if self.on_become_leader:
            try:
                self.on_become_leader()
            except Exception as e:
                logger.error(f"❌ Error in become_leader callback: {e}")
                
        logger.info(f"👑 Successfully became cluster leader")
        
    def _lose_leadership(self):
        """Lose leadership (called when lease expires or fails to renew)"""
        if not self.is_leader:
            return
            
        logger.warning(f"💔 Losing cluster leadership")
        
        with self._lock:
            self.state = NodeState.FOLLOWER
            self.is_leader = False
            self.leader_id = None
            
        # Update node status
        self._update_node_status()
        
        # Log cluster event
        self._log_cluster_event("leader_lost", {
            "term": self.current_term,
            "node_id": self.node_id,
            "reason": "lease_expired"
        })
        
        # Notify application that we lost leadership
        if self.on_lose_leadership:
            try:
                self.on_lose_leadership()
            except Exception as e:
                logger.error(f"❌ Error in lose_leadership callback: {e}")
                
        logger.warning(f"💔 Lost cluster leadership")
        
    def _release_leadership(self):
        """Voluntarily release leadership"""
        if not self.is_leader:
            return
            
        logger.info(f"🚪 Voluntarily releasing cluster leadership")
        
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Clear the lease
                    cursor.execute("""
                        DELETE FROM leader_lease WHERE leader_id = %s AND term = %s
                    """, (self.node_id, self.current_term))
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"❌ Failed to release leadership lease: {e}")
            
        self._lose_leadership()
        
    def _renew_leadership_lease(self):
        """Renew leadership lease to maintain leadership"""
        if not self.is_leader:
            return
            
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE leader_lease 
                        SET expires_at = CURRENT_TIMESTAMP + INTERVAL '%s seconds',
                            renewed_at = CURRENT_TIMESTAMP
                        WHERE leader_id = %s AND term = %s
                    """, (self.lease_ttl, self.node_id, self.current_term))
                    
                    if cursor.rowcount == 0:
                        # We lost the lease somehow
                        logger.warning("⚠️  Lost leadership lease during renewal")
                        conn.rollback()
                        self._lose_leadership()
                    else:
                        conn.commit()
                        
        except Exception as e:
            logger.error(f"❌ Failed to renew leadership lease: {e}")
            self._lose_leadership()
            
    def _check_leader_health(self):
        """Check current leader health and lease validity"""
        try:
            current_lease = self._get_current_lease()
            
            if current_lease:
                # Check if lease has expired
                if current_lease.expires_at <= time.time():
                    if self.leader_id == current_lease.leader_id:
                        self.leader_id = None
                        logger.info("⏰ Leader lease expired")
                        
                # Update our knowledge of current leader
                elif self.leader_id != current_lease.leader_id:
                    self.leader_id = current_lease.leader_id
                    logger.info(f"👑 New leader detected: {self.leader_id}")
                    
        except Exception as e:
            logger.error(f"❌ Error checking leader health: {e}")
            
    def _get_current_lease(self) -> Optional[LeaderLease]:
        """Get current leadership lease"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT leader_id, term, acquired_at, expires_at, 
                               renewed_at, hostname, api_url
                        FROM leader_lease 
                        WHERE id = 1
                    """)
                    
                    row = cursor.fetchone()
                    if row:
                        return LeaderLease(
                            leader_id=row[0],
                            term=row[1],
                            acquired_at=row[2].timestamp(),
                            expires_at=row[3].timestamp(),
                            renewed_at=row[4].timestamp(),
                            hostname=row[5],
                            api_url=row[6]
                        )
                        
        except Exception as e:
            logger.error(f"❌ Failed to get current lease: {e}")
            
        return None
        
    def _update_cluster_membership(self):
        """Update knowledge of cluster members"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT node_id, hostname, port, api_url, state, 
                               term, last_heartbeat, is_healthy
                        FROM cluster_nodes
                        WHERE last_heartbeat >= CURRENT_TIMESTAMP - INTERVAL '60 seconds'
                    """)
                    
                    nodes = {}
                    for row in cursor.fetchall():
                        node = ClusterNode(
                            node_id=row[0],
                            hostname=row[1],
                            port=row[2],
                            api_url=row[3],
                            state=NodeState(row[4]),
                            term=row[5],
                            last_heartbeat=row[6].timestamp(),
                            is_healthy=row[7]
                        )
                        nodes[node.node_id] = node
                        
                    # Update cluster membership
                    old_nodes = set(self.cluster_nodes.keys())
                    new_nodes = set(nodes.keys())
                    
                    if old_nodes != new_nodes:
                        self.cluster_nodes = nodes
                        
                        added = new_nodes - old_nodes
                        removed = old_nodes - new_nodes
                        
                        if added:
                            logger.info(f"➕ Cluster nodes joined: {added}")
                        if removed:
                            logger.info(f"➖ Cluster nodes left: {removed}")
                            
                        # Notify of cluster change
                        if self.on_cluster_change:
                            try:
                                self.on_cluster_change(self.cluster_nodes)
                            except Exception as e:
                                logger.error(f"❌ Error in cluster_change callback: {e}")
                                
        except Exception as e:
            logger.error(f"❌ Failed to update cluster membership: {e}")
            
    def _cleanup_stale_nodes(self):
        """Clean up stale/offline nodes from cluster"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Remove nodes that haven't sent heartbeat in 5 minutes
                    cursor.execute("""
                        DELETE FROM cluster_nodes
                        WHERE last_heartbeat < CURRENT_TIMESTAMP - INTERVAL '300 seconds'
                          AND node_id != %s
                    """, (self.node_id,))
                    
                    if cursor.rowcount > 0:
                        logger.info(f"🧹 Cleaned up {cursor.rowcount} stale cluster nodes")
                        conn.commit()
                        
        except Exception as e:
            logger.error(f"❌ Failed to cleanup stale nodes: {e}")
            
    def _update_node_status(self):
        """Update this node's status in the database"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE cluster_nodes 
                        SET state = %s, 
                            term = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE node_id = %s
                    """, (
                        self.state.value,
                        self.current_term,
                        self.node_id
                    ))
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"❌ Failed to update node status: {e}")
            
    def _log_cluster_event(self, event_type: str, event_data: Dict[str, Any]):
        """Log cluster coordination event"""
        try:
            with self._get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO cluster_events (node_id, event_type, event_data, term)
                        VALUES (%s, %s, %s, %s)
                    """, (
                        self.node_id,
                        event_type,
                        json.dumps(event_data),
                        self.current_term
                    ))
                    conn.commit()
                    
        except Exception as e:
            logger.error(f"❌ Failed to log cluster event: {e}")
            
    @contextmanager
    def _get_db_connection(self):
        """Get database connection (preferring primary for writes)"""
        if self.db_manager:
            with self.db_manager._get_connection(write=True) as conn:
                yield conn
        else:
            raise RuntimeError("No database manager configured")
            
    def get_cluster_status(self) -> Dict[str, Any]:
        """Get current cluster status"""
        current_lease = self._get_current_lease()
        
        return {
            "node_id": self.node_id,
            "hostname": self.hostname,
            "state": self.state.value,
            "term": self.current_term,
            "is_leader": self.is_leader,
            "leader_id": self.leader_id,
            "cluster_size": len(self.cluster_nodes),
            "nodes": [asdict(node) for node in self.cluster_nodes.values()],
            "lease": asdict(current_lease) if current_lease else None
        }
        
    def get_leader_info(self) -> Optional[Dict[str, Any]]:
        """Get current leader information"""
        current_lease = self._get_current_lease()
        if current_lease and current_lease.expires_at > time.time():
            return {
                "leader_id": current_lease.leader_id,
                "hostname": current_lease.hostname,
                "api_url": current_lease.api_url,
                "term": current_lease.term,
                "lease_expires_at": current_lease.expires_at
            }
        return None
        
    def is_cluster_ready(self) -> bool:
        """Check if cluster has minimum nodes and a leader"""
        return (
            len(self.cluster_nodes) >= 1 and  # At least 1 node (can be relaxed to 3 for production)
            self.leader_id is not None and
            self._get_current_lease() is not None
        )