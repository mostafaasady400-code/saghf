"""
Divar Health & Deletion Watcher for Saghf Platform.
Asynchronously and concurrently verifies listing presence on Divar to detect deletions,
expired listings, or removed owner posts with high concurrency and zero blocking.
"""

from __future__ import annotations

import time
import requests
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json'
}


class DivarHealthWatcher:
    """
    پایشگر سلامت و راستی‌آزمایی وضعیت زنده‌بودن آگهی‌های دیوار.
    شناسایی سریع فایل‌های واگذارشده یا حذف‌شده با اجرای هم‌روند چندنخی (Multithreaded).
    """

    @classmethod
    def check_token_status(cls, token: str, timeout: float = 3.5) -> Tuple[str, str]:
        """
        استعلام وضعیت یک توکن در دیوار.
        خروجی: (token, status) که status یکی از مقادیر 'alive', 'deleted', 'error' است.
        """
        clean_tok = str(token).replace('divar_', '').strip()
        if '/' in clean_tok:
            clean_tok = clean_tok.rstrip('/').split('/')[-1]

        if not clean_tok or len(clean_tok) < 6:
            return token, 'invalid'

        url = f"https://api.divar.ir/v8/posts-v2/web/{clean_tok}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                return token, 'alive'
            elif resp.status_code == 404:
                return token, 'deleted'
            else:
                return token, f'status_{resp.status_code}'
        except Exception:
            return token, 'error'

    @classmethod
    def sync_all_database_listings(cls, max_workers: int = 8, limit: int = 150) -> Dict[str, Any]:
        """
        استعلام فوق‌سریع و هم‌روند وضعیت تمام فایل‌های ثبت‌شده در دیتابیس با ThreadPool.
        """
        from app import create_app
        from database.db import db
        from database.models import Property

        app = create_app()
        with app.app_context():
            props = Property.query.limit(limit).all()
            if not props:
                return {'total': 0, 'alive': 0, 'deleted': 0, 'errors': 0}

            prop_map = {}
            for p in props:
                tok = str(p.source_id or '').replace('divar_', '').strip()
                if not tok and p.source_url:
                    tok = p.source_url.rstrip('/').split('/')[-1]
                if tok and len(tok) >= 5:
                    prop_map[tok] = p

            tokens = list(prop_map.keys())
            alive_count = 0
            deleted_count = 0
            error_count = 0

            # اجرای هم‌روند با ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(cls.check_token_status, t): t for t in tokens}
                for fut in as_completed(futures):
                    tok, st = fut.result()
                    p = prop_map.get(tok)
                    if not p:
                        continue

                    if st == 'alive':
                        p.is_divar_deleted = False
                        alive_count += 1
                    elif st == 'deleted':
                        p.is_divar_deleted = True
                        if not p.divar_deleted_at:
                            p.divar_deleted_at = datetime.utcnow()
                        deleted_count += 1
                    else:
                        error_count += 1

            db.session.commit()

            return {
                'total_checked': len(tokens),
                'alive': alive_count,
                'deleted': deleted_count,
                'errors': error_count,
                'synced_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
