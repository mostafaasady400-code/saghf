import os
import threading
import time
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

class ProxyManager:
    """
    مدیریت و چرخش استخر پراکسی‌های مسکونی و موبایلی با سنجش سلامت،
    حذف خودکار پراکسی‌های معیوب (Circuit Breaker) و بازپروری ادواری (Auto-Rehabilitation)
    """
    def __init__(self, proxies: Optional[List[str]] = None, cooldown_seconds: float = 300.0):
        if proxies is None:
            env_proxies = os.getenv('CRAWLER_PROXIES') or os.getenv('PROXY_POOL') or ''
            proxies = [p.strip() for p in env_proxies.split(',') if p.strip()]
        self.proxies = proxies or []
        self.cooldown_seconds = cooldown_seconds
        self.current_idx = 0
        self.lock = threading.Lock()
        self.stats: Dict[str, Dict[str, Any]] = {
            p: {"success": 0, "failures": 0, "last_used": 0, "is_healthy": True}
            for p in self.proxies
        }

    def get_proxy(self) -> Optional[str]:
        with self.lock:
            now = time.time()
            # بازپروری خودکار پراکسی‌های خنک‌شده (Half-Open Circuit Breaker)
            for p in self.proxies:
                if not self.stats[p]["is_healthy"]:
                    if now - self.stats[p]["last_used"] >= self.cooldown_seconds:
                        self.stats[p]["is_healthy"] = True
                        self.stats[p]["failures"] = 0
                        logger.info(f"[ProxyManager] پراکسی {p} پس از {self.cooldown_seconds} ثانیه بازپروری شد.")

            healthy_proxies = [p for p in self.proxies if self.stats[p]["is_healthy"]]
            if not healthy_proxies:
                return None  # حالت اتصال مستقیم (Direct Connection)

            self.current_idx = (self.current_idx + 1) % len(healthy_proxies)
            chosen = healthy_proxies[self.current_idx]
            self.stats[chosen]["last_used"] = now
            return chosen

    def report_success(self, proxy: Optional[str]):
        if not proxy or proxy not in self.stats:
            return
        with self.lock:
            self.stats[proxy]["success"] += 1
            self.stats[proxy]["failures"] = 0

    def report_failure(self, proxy: Optional[str]):
        if not proxy or proxy not in self.stats:
            return
        with self.lock:
            self.stats[proxy]["failures"] += 1
            self.stats[proxy]["last_used"] = time.time()
            if self.stats[proxy]["failures"] >= 3:
                self.stats[proxy]["is_healthy"] = False
                logger.warning(f"[ProxyManager] پراکسی {proxy} به علت ۳ خطای متوالی موقتاً غیرفعال شد.")

    def add_proxy(self, proxy_url: str):
        with self.lock:
            if proxy_url not in self.proxies:
                self.proxies.append(proxy_url)
                self.stats[proxy_url] = {"success": 0, "failures": 0, "last_used": 0, "is_healthy": True}

    def get_pool_status(self) -> Dict[str, Any]:
        """گزارش آماری ظرفیت و سلامت استخر پراکسی‌ها"""
        with self.lock:
            total = len(self.proxies)
            healthy = sum(1 for p in self.proxies if self.stats[p]["is_healthy"])
            return {
                "total_proxies": total,
                "healthy_proxies": healthy,
                "degraded_proxies": total - healthy,
                "health_rate_pct": round((healthy / total * 100), 1) if total > 0 else 100.0,
                "circuit_breaker_active": healthy < total
            }
