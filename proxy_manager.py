import requests
import random
import time
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class ProxyIP:
    ip: str
    port: int
    country: str
    last_used: datetime
    success_count: int
    failure_count: int
    is_active: bool
    speed: float  # Response time in seconds
    source: str   # 'request_ip' or 'proxy_pool'

class ProxyManager:
    def __init__(self):
        self.proxies: List[ProxyIP] = []
        self.user_ips: Dict[str, Dict] = {}  # Store user IPs and their usage stats
        self.lock = threading.Lock()
        self.max_user_ips = 1000
        self.proxy_pool_urls = [
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"
        ]
        
        # Public proxy services as fallback
        self.public_proxies = [
            {"ip": "154.16.202.22", "port": 3128, "country": "DE"},
            {"ip": "154.16.202.97", "port": 3128, "country": "DE"},
            {"ip": "45.95.147.200", "port": 8080, "country": "DE"},
            {"ip": "43.153.2.120", "port": 3128, "country": "US"},
            {"ip": "45.95.147.218", "port": 8080, "country": "DE"},
        ]
        
        self.initialize_proxies()
    
    def initialize_proxies(self):
        """Initialize with public proxies"""
        for proxy in self.public_proxies:
            self.add_proxy(
                ip=proxy["ip"],
                port=proxy["port"],
                country=proxy["country"],
                source="public"
            )
        
        logger.info(f"Initialized with {len(self.proxies)} proxies")
    
    def add_proxy(self, ip: str, port: int, country: str = "Unknown", source: str = "unknown"):
        """Add a new proxy to the pool"""
        with self.lock:
            proxy = ProxyIP(
                ip=ip,
                port=port,
                country=country,
                last_used=datetime.utcnow() - timedelta(hours=1),
                success_count=0,
                failure_count=0,
                is_active=True,
                speed=1.0,
                source=source
            )
            self.proxies.append(proxy)
    
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
                    "speed": 1.0,
                    "type": "user_ip"
                }
                
                # Convert to proxy format for unified selection
                self.add_proxy(ip, 80, "UserIP", source="request_ip")
                
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
            # Also remove from proxies list
            self.proxies = [p for p in self.proxies if not (p.source == "request_ip" and p.ip == ip)]
        
        logger.info(f"Cleaned up {len(old_ips)} old user IPs")
    
    def get_best_proxy(self, exclude_ip: str = None) -> Optional[ProxyIP]:
        """Get the best available proxy based on performance"""
        with self.lock:
            # Filter active proxies
            active_proxies = [
                p for p in self.proxies
                if p.is_active and (exclude_ip is None or p.ip != exclude_ip)
            ]
            
            if not active_proxies:
                logger.warning("No active proxies available")
                return None
            
            # Score proxies based on performance
            scored_proxies = []
            for proxy in active_proxies:
                # Calculate score (higher is better)
                success_rate = proxy.success_count / max(1, proxy.success_count + proxy.failure_count)
                time_since_use = (datetime.utcnow() - proxy.last_used).total_seconds()
                
                # User IPs get priority
                priority = 2.0 if proxy.source == "request_ip" else 1.0
                
                score = (
                    success_rate * 0.5 +
                    (1 / (proxy.speed + 0.1)) * 0.3 +  # Faster is better
                    min(time_since_use / 3600, 24) * 0.1 +  # Not recently used
                    priority * 0.1
                )
                
                scored_proxies.append((score, proxy))
            
            # Sort by score (descending)
            scored_proxies.sort(key=lambda x: x[0], reverse=True)
            
            # Return top 3 randomly to avoid overusing one proxy
            top_n = min(3, len(scored_proxies))
            selected = random.choice(scored_proxies[:top_n])[1]
            
            # Update last used time
            selected.last_used = datetime.utcnow()
            
            return selected
    
    def get_user_ip_proxy(self, user_ip: str) -> Optional[ProxyIP]:
        """Get proxy configuration for a specific user IP"""
        with self.lock:
            # Check if this user IP is in our pool
            for proxy in self.proxies:
                if proxy.ip == user_ip and proxy.source == "request_ip":
                    proxy.last_used = datetime.utcnow()
                    return proxy
            
            # If not, create one
            self.add_user_ip(user_ip)
            
            # Return the newly created proxy
            for proxy in self.proxies:
                if proxy.ip == user_ip and proxy.source == "request_ip":
                    return proxy
            
            return None
    
    def update_proxy_performance(self, ip: str, success: bool, response_time: float):
        """Update proxy performance metrics"""
        with self.lock:
            for proxy in self.proxies:
                if proxy.ip == ip:
                    if success:
                        proxy.success_count += 1
                        # Update speed with exponential moving average
                        proxy.speed = 0.7 * proxy.speed + 0.3 * response_time
                    else:
                        proxy.failure_count += 1
                        # If too many failures, mark as inactive
                        if proxy.failure_count > 5 and proxy.success_count < 3:
                            proxy.is_active = False
                    
                    proxy.last_used = datetime.utcnow()
                    break
            
            # Also update user IPs
            if ip in self.user_ips:
                if success:
                    self.user_ips[ip]["success_count"] += 1
                else:
                    self.user_ips[ip]["failure_count"] += 1
                self.user_ips[ip]["last_used"] = datetime.utcnow()
                self.user_ips[ip]["total_requests"] += 1
    
    def refresh_proxy_pool(self):
        """Refresh proxy pool from external sources"""
        logger.info("Refreshing proxy pool...")
        new_proxies = []
        
        for url in self.proxy_pool_urls:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    lines = response.text.strip().split('\n')
                    for line in lines:
                        line = line.strip()
                        if ':' in line:
                            ip, port = line.split(':')[:2]
                            try:
                                port = int(port)
                                new_proxies.append({
                                    "ip": ip.strip(),
                                    "port": port,
                                    "country": "Unknown",
                                    "source": "proxy_pool"
                                })
                            except:
                                continue
            except Exception as e:
                logger.error(f"Failed to fetch proxies from {url}: {str(e)}")
        
        # Add new proxies that we don't already have
        existing_ips = {f"{p.ip}:{p.port}" for p in self.proxies}
        added = 0
        
        for proxy in new_proxies:
            key = f"{proxy['ip']}:{proxy['port']}"
            if key not in existing_ips:
                self.add_proxy(
                    ip=proxy["ip"],
                    port=proxy["port"],
                    country=proxy["country"],
                    source=proxy["source"]
                )
                added += 1
        
        logger.info(f"Added {added} new proxies to pool")
        return added
    
    def get_stats(self) -> Dict:
        """Get proxy pool statistics"""
        with self.lock:
            total = len(self.proxies)
            active = sum(1 for p in self.proxies if p.is_active)
            user_ips = sum(1 for p in self.proxies if p.source == "request_ip")
            proxy_ips = total - user_ips
            
            avg_success = 0
            if total > 0:
                total_success = sum(p.success_count for p in self.proxies)
                total_attempts = sum(p.success_count + p.failure_count for p in self.proxies)
                avg_success = (total_success / total_attempts * 100) if total_attempts > 0 else 0
            
            return {
                "total_proxies": total,
                "active_proxies": active,
                "user_ips": user_ips,
                "proxy_ips": proxy_ips,
                "success_rate": f"{avg_success:.1f}%",
                "user_ip_count": len(self.user_ips),
                "last_refresh": datetime.utcnow().isoformat()
            }
    
    def run_background_tasks(self):
        """Run background maintenance tasks"""
        # Refresh proxy pool every 30 minutes
        while True:
            time.sleep(1800)  # 30 minutes
            try:
                self.refresh_proxy_pool()
                self.cleanup_old_user_ips()
            except Exception as e:
                logger.error(f"Background task error: {str(e)}")

# Global proxy manager instance
proxy_manager = ProxyManager()

# Start background thread for proxy maintenance
background_thread = threading.Thread(
    target=proxy_manager.run_background_tasks,
    daemon=True
)
background_thread.start()
