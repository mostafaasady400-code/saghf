"""
کلاینت اختصاصی اتصال مستقیم به سرور n8n از طریق پروتکل MCP (Model Context Protocol)
پشتیبانی از ۵۴ ابزار رسمی n8n جهت مدیریت ورکفلوها، اجرای نودها، همگام‌سازی لیدها و اتوماسیون
"""

import json
import logging
import urllib.request
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class N8nMcpClient:
    DEFAULT_URL = "https://kian1377.app.n8n.cloud/mcp-server/http"
    DEFAULT_TOKEN = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJjYTE1ODhmMC1hMzNiLTRjZGEtOGEzZS1mOTcxNTQwNmY2ZWEiLCJpc3MiOiJuOG4iLCJhdWQiOiJtY3Atc2VydmVyLWFwaSIsImp0aSI6ImY0ODRhOTg3LWE3NTItNDA5NS1iYzllLTY0ZmE2ZmEzMWU5YSIsImlhdCI6MTc4OTU4NDcxNH0.qgoNkHKcWE6JFDYUgbIoWHsg1-BQVQOEdC4CLcC_UyY"

    def __init__(self, url: Optional[str] = None, token: Optional[str] = None):
        self.url = url or self.DEFAULT_URL
        self.token = token or self.DEFAULT_TOKEN
        self.session_id: Optional[str] = None
        self._initialized = False

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            'Authorization': self.token,
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream'
        }
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        return headers

    def initialize(self) -> Dict[str, Any]:
        """ارسال درخواست دست‌تکانی اولیه پروتکل MCP"""
        payload = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2024-11-05',
                'capabilities': {},
                'clientInfo': {
                    'name': 'saghf-real-estate-agent',
                    'version': '2.0.0'
                }
            }
        }
        res = self._post_jsonrpc(payload)
        self._initialized = True
        return res

    def list_tools(self) -> List[Dict[str, Any]]:
        """کشف و دریافت فهرست کلیه ابزارهای قابل دسترس در سرور n8n"""
        if not self._initialized:
            self.initialize()

        payload = {
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'tools/list',
            'params': {}
        }
        res = self._post_jsonrpc(payload)
        return res.get('result', {}).get('tools', [])

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """فراخوانی هریک از ابزارهای n8n از طریق پروتکل MCP"""
        if not self._initialized:
            self.initialize()

        payload = {
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'tools/call',
            'params': {
                'name': tool_name,
                'arguments': arguments or {}
            }
        }
        return self._post_jsonrpc(payload)

    # توابع میان‌بر پرکاربرد برای سهولت کارشناسان و ماژول‌های سیستم
    def search_workflows(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """جستجوی ورکفلوهای موجود در n8n"""
        args = {}
        if query:
            args['query'] = query
        resp = self.call_tool('search_workflows', args)
        content = resp.get('result', {}).get('structuredContent', {}).get('data', [])
        if not content:
            # fallback به محتوای متنی
            raw_c = resp.get('result', {}).get('content', [])
            if raw_c and isinstance(raw_c[0], dict) and 'text' in raw_c[0]:
                try:
                    parsed = json.loads(raw_c[0]['text'])
                    content = parsed.get('data', [])
                except Exception:
                    pass
        return content

    def execute_workflow(self, workflow_id: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """اجرای یک ورکفلو با شناسه آن"""
        args = {'workflowId': workflow_id}
        if data:
            args['data'] = data
        return self.call_tool('execute_workflow', args)

    def search_nodes(self, query: str) -> List[Dict[str, Any]]:
        """جستجوی نودها و سرویس‌های قابل استفاده در n8n"""
        return self.call_tool('search_nodes', {'query': query})

    def _post_jsonrpc(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.url, data=data_bytes, headers=self._get_headers(), method='POST')
        with urllib.request.urlopen(req, timeout=25) as resp:
            new_sess = resp.headers.get('Mcp-Session-Id')
            if new_sess:
                self.session_id = new_sess
            body = resp.read().decode('utf-8')
            for line in body.splitlines():
                if line.startswith('data:'):
                    return json.loads(line[5:].strip())
            try:
                return json.loads(body)
            except Exception:
                return {'raw': body}

# نمونه سینگلتون جهت استفاده عمومی در پروژه
n8n_client = N8nMcpClient()
