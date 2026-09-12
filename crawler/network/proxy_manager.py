import threading
import time
from typing import List, Optional, Dict

class ProxyManager:
    """
    مدیریت و چرخش استخر پراکسی‌های مسکونی و موبایلی با سنجش سلامت و حذف خودکار پراکسی‌های معیوب
    """
    def __init__(self, proxies: Optional[List[str]] = None):
        self.proxies = proxies or []
        self.current_idx = 0
        self.lock = threading.Lock()
        self.stats: Dict[str, Dict[str, Any]] = {
            p: {"success": 0, "failures": 0, "last_used": 0, "is_healthy": True}
            for p in self.proxies
        }

    def get_proxy(self) -> Optional[str]:
        with self.lock:
            healthy_proxies = [p for p in self.proxies if self.stats[p]["is_healthy"]]
            if not healthy_proxies:
                return None # حالت اتصال مستقیم (Direct Connection)
            
            self.current_idx = (self.current_idx + 1) % len(healthy_proxies)
            chosen = healthy_proxies[self.current_idx]
            self.stats[chosen]["last_used"] = time.time()
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
            if self.stats[proxy]["failures"] >= 3:
                self.stats[proxy]["is_healthy"] = False
                print(f"[ProxyManager] پراکسی {proxy} به علت ۳ خطای متوالی موقتاً غیرفعال شد.")

    def add_proxy(self, proxy_url: str):
        with self.lock:
            if proxy_url not in self.proxies:
                self.proxies.append(proxy_url)
                self.stats[proxy_url] = {"success": 0, "failures": 0, "last_used": 0, "is_healthy": True}
