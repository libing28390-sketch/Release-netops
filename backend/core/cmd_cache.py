import time
import re
import threading
import logging

logger = logging.getLogger(__name__)

# Global memory cache for device command outputs
# Structure: { (device_ip, command): (output, expire_time) }
_CMD_CACHE = {}
_CACHE_LOCK = threading.Lock()

def get_cached_command(device_ip: str, command: str) -> str | None:
    """
    Get cached command output if it exists and has not expired.
    """
    device_ip = (device_ip or "").strip()
    command = (command or "").strip()
    
    with _CACHE_LOCK:
        if (device_ip, command) in _CMD_CACHE:
            output, expire_time = _CMD_CACHE[(device_ip, command)]
            if time.time() < expire_time:
                logger.debug(f"[CmdCache] Cache HIT for device {device_ip}, command: {command}")
                return output
            else:
                # Expired, clean up
                del _CMD_CACHE[(device_ip, command)]
    return None

def set_cached_command(device_ip: str, command: str, output: str, ttl: int = None):
    """
    Cache a command output with a TTL.
    If TTL is None, it will be automatically calculated based on the command type.
    """
    device_ip = (device_ip or "").strip()
    command = (command or "").strip()
    
    if ttl is None:
        ttl = get_suggested_ttl(command)
        
    if ttl <= 0:
        return
        
    with _CACHE_LOCK:
        _CMD_CACHE[(device_ip, command)] = (output, time.time() + ttl)
        logger.debug(f"[CmdCache] Cached command output for {device_ip} (TTL: {ttl}s), command: {command}")

def get_suggested_ttl(command: str) -> int:
    """
    Determine the suggested TTL in seconds for a given command.
    """
    cmd_lower = command.lower()
    
    # 1. Performance and health status changes quickly, cache briefly
    if any(k in cmd_lower for k in ('cpu', 'mem', 'processes', 'standby', 'vrrp', 'health')):
        return 15  # 15 seconds for performance metrics
        
    # 2. Topology, Routing, ARP, LLDP, MAC tables change rarely, cache longer
    if any(k in cmd_lower for k in ('route', 'cef', 'fib', 'bgp', 'arp', 'lldp', 'cdp', 'mac', 'interface brief', 'acl', 'access-list', 'traffic-policy')):
        return 300  # 5 minutes for routing/topology
        
    # 3. Default TTL
    return 60

def clear_cmd_cache():
    """Clear all cached command outputs."""
    with _CACHE_LOCK:
        _CMD_CACHE.clear()
        logger.info("[CmdCache] Command cache cleared.")
