import time
import random
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional
import threading

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self):
        self.user_ips = {}
        self.public_proxies = [
            {"ip": "154.16.202.22", "port": 3128, "country": "DE"},
            {"ip": "154.16.202.97", "port": 3128, "country": "DE"},
        ]
        self.lock = threading.Lock()
        self.max_user_ips = 100
        
        logger.info("ProxyManager initialized")
    
    def add_user_ip(self, ip: str, user_agent: str = ""):
        """Add a user's IP to the pool"""
        with self.lock:
            if ip not in self.user_ips:
                self.user_ips[ip] = {
                    "ip": ip,
                    "user_agent": user_agent,
                    "added_at": datetime.utcnow(),
                    "last_used": datetime.utcnow() - timedelta(hours=1),
                    "success_count": 0,
                    "failure_count": 0,
                    "total_requests": 0,
                    "is_active": True,
                }
                
                logger.info(f"Added user IP to pool: {ip}")
                
                # Clean old user IPs if we have too many
                if len(self.user_ips) > self.max_user_ips:
                    self.cleanup_old_user_ips()
    
    def cleanup_old_user_ips(self):
        """Remove old/inactive user IPs"""
        cutoff = datetime.utcnow() - timedelta(days=1)
        old_ips = [
            ip for ip, data in self.user_ips.items()
            if data["last_used"] < cutoff or data["failure_count"] > 10
        ]
        
        for ip in old_ips:
            del self.user_ips[ip]
        
        logger.info(f"Cleaned up {len(old_ips)} old user IPs")
    
    def get_stats(self) -> Dict:
        """Get proxy pool statistics"""
        with self.lock:
            total = len(self.user_ips) + len(self.public_proxies)
            
            # Calculate success rate
            total_success = sum(data["success_count"] for data in self.user_ips.values())
            total_failures = sum(data["failure_count"] for data in self.user_ips.values())
            total_attempts = total_success + total_failures
            
            success_rate = (total_success / total_attempts * 100) if total_attempts > 0 else 0
            
            return {
                "total_proxies": total,
                "user_ips": len(self.user_ips),
                "public_proxies": len(self.public_proxies),
                "success_rate": f"{success_rate:.1f}%",
                "last_update": datetime.utcnow().isoformat()
            }
    
    def update_ip_performance(self, ip: str, success: bool):
        """Update IP performance metrics"""
        with self.lock:
            if ip in self.user_ips:
                if success:
                    self.user_ips[ip]["success_count"] += 1
                else:
                    self.user_ips[ip]["failure_count"] += 1
                
                self.user_ips[ip]["last_used"] = datetime.utcnow()
                self.user_ips[ip]["total_requests"] += 1

# Global proxy manager instance
proxy_manager = ProxyManager()
