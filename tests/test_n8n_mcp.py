"""
تست اعتبارسنجی اتصال به سرور n8n از طریق پروتکل MCP
بررسی کشف ابزارها و قابلیت‌های مدیریت ورکفلوها
"""

import unittest
from services.n8n_mcp_client import N8nMcpClient

class TestN8nMcp(unittest.TestCase):

    def setUp(self):
        self.client = N8nMcpClient()

    def test_01_mcp_initialize(self):
        """تست دست‌تکانی پروتکل MCP با سرور n8n"""
        res = self.client.initialize()
        self.assertIn('result', res)
        server_info = res['result'].get('serverInfo', {})
        self.assertEqual(server_info.get('name'), 'n8n MCP Server')

    def test_02_tool_discovery(self):
        """تست کشف کامل ۵۴ ابزار سرور n8n"""
        tools = self.client.list_tools()
        self.assertGreaterEqual(len(tools), 50)
        tool_names = [t['name'] for t in tools]
        
        # ابزارهای کلیدی مدیریت ورکفلو و نودها
        expected_tools = [
            'search_workflows',
            'execute_workflow',
            'get_workflow_details',
            'search_nodes',
            'publish_workflow',
            'search_agents'
        ]
        for et in expected_tools:
            self.assertIn(et, tool_names)

    def test_03_search_workflows_action(self):
        """تست اجرای ابزار search_workflows از طریق tools/call"""
        workflows = self.client.search_workflows()
        self.assertIsInstance(workflows, list)
        self.assertTrue(bool(workflows[0].get('id')))

if __name__ == '__main__':
    unittest.main()
