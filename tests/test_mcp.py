import json
import os
import subprocess
import unittest

SERVER = os.path.join(os.path.dirname(__file__), "..", "mcp", "modeldock_mcp.py")


def talk(messages, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    proc = subprocess.run(["/usr/bin/python3", SERVER],
                          input="\n".join(json.dumps(m) for m in messages) + "\n",
                          capture_output=True, text=True, timeout=30, env=e)
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]


class TestMcpProtocol(unittest.TestCase):
    def test_handshake_and_tools(self):
        out = talk([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ])
        self.assertEqual(len(out), 3)          # notification gets no reply
        init = next(m for m in out if m["id"] == 1)
        self.assertEqual(init["result"]["serverInfo"]["name"], "modeldock")
        tools = next(m for m in out if m["id"] == 2)["result"]["tools"]
        self.assertEqual(len(tools), 10)
        self.assertIn("search_models", [t["name"] for t in tools])
        for t in tools:                        # every tool must carry a schema
            self.assertIn("inputSchema", t)

    def test_app_not_running_is_friendly_error(self):
        out = talk([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "system_info", "arguments": {}}},
        ], env={"MODELDOCK_URL": "http://127.0.0.1:59999"})
        call = next(m for m in out if m["id"] == 2)
        self.assertTrue(call["result"]["isError"])
        self.assertIn("start.command", call["result"]["content"][0]["text"])

    def test_unknown_method_errors(self):
        out = talk([{"jsonrpc": "2.0", "id": 9, "method": "nope/nope"}])
        self.assertEqual(out[0]["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
