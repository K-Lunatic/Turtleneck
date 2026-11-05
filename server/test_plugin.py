"""Offline MCP/OAuth integration tests: no real school credentials or network traffic."""
import base64
import hashlib
import io
import json
import re
import tempfile
import time
import unittest
from urllib.parse import urlencode, urlsplit, parse_qs
from unittest.mock import patch

from server.plugin import PluginGateway
from server.test_app import FakeProvider, FakeSession

CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
VERIFIER = "pkce-verifier-" + "a" * 48
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


class PluginGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = PluginGateway("https://tls.example.test", "actions-client",
                                 "x" * 48, ["https://chatgpt.com/aip/g-test/oauth/callback"],
                                 self.temp.name, FakeSession)
        self.provider = patch("server.app.MoodleTLSProvider", FakeProvider)
        self.provider.start()

    def tearDown(self):
        for _ in range(200):
            if not any(item["running"] for item in self.app.accounts.values()):
                break
            time.sleep(.005)
        self.provider.stop()
        self.temp.cleanup()

    def request(self, path, method="GET", data=None, token=None, query=None, form=False):
        raw = (urlencode(data or {}).encode() if form else
               json.dumps(data or {}, ensure_ascii=False).encode())
        env = {"REQUEST_METHOD": method, "PATH_INFO": path,
               "QUERY_STRING": urlencode(query or {}),
               "CONTENT_TYPE": "application/x-www-form-urlencoded" if form else "application/json",
               "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw)}
        if token:
            env["HTTP_AUTHORIZATION"] = "Bearer " + token
        result = {}
        def start(status, headers):
            result.update(status=int(status.split()[0]), headers=dict(headers))
        response = b"".join(self.app(env, start)).decode()
        result["body"] = (json.loads(response) if response and
                          result["headers"]["Content-Type"].startswith("application/json")
                          else response)
        return result

    def registration(self):
        response = self.request("/mcp/oauth/register", "POST", {
            "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
        })
        self.assertEqual(response["status"], 201)
        return response["body"]["client_id"]

    def authorization(self, client):
        response = self.request("/mcp/oauth/authorize", query={
            "client_id": client, "redirect_uri": CALLBACK,
            "response_type": "code", "scope": "academic:read academic:write",
            "state": "state-123", "code_challenge": CHALLENGE,
            "code_challenge_method": "S256", "resource": "https://tls.example.test/mcp",
        })
        self.assertEqual(response["status"], 200)
        return re.search(r'name="ticket" value="([^"]+)"', response["body"]).group(1)

    def code(self, client, username="alice"):
        ticket = self.authorization(client)
        response = self.request("/mcp/oauth/login", "POST", {
            "ticket": ticket, "username": username, "password": "fixture-password",
        }, form=True)
        self.assertEqual(response["status"], 302)
        self.assertIn("state=state-123", response["headers"]["Location"])
        return parse_qs(urlsplit(response["headers"]["Location"]).query)["code"][0]

    def exchange(self, client, code, verifier=VERIFIER):
        return self.request("/mcp/oauth/token", "POST", {
            "grant_type": "authorization_code", "client_id": client,
            "code": code, "code_verifier": verifier, "redirect_uri": CALLBACK,
        }, form=True)

    def connect(self, client, username="alice"):
        result = self.exchange(client, self.code(client, username))
        self.assertEqual(result["status"], 200)
        for _ in range(200):
            if not self.app.accounts[username]["running"]:
                break
            time.sleep(.005)
        self.assertIsNone(self.app.accounts[username]["error"])
        return result["body"]

    def call(self, token, name, args=None):
        return self.request("/mcp", "POST", {
            "jsonrpc": "2.0", "id": "tool-test", "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        }, token)

    def test_discovery_and_secure_registration(self):
        resource = self.request("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(resource["body"]["resource"], "https://tls.example.test/mcp")
        auth_server = self.request("/.well-known/oauth-authorization-server")
        self.assertEqual(auth_server["body"]["issuer"], "https://tls.example.test")
        self.assertIn("S256", auth_server["body"]["code_challenge_methods_supported"])
        for bad in ["https://evil.example/oauth", "http://chatgpt.com/connector_platform_oauth_redirect",
                    "https://chatgpt.com.evil.org/connector_platform_oauth_redirect"]:
            self.assertEqual(self.request("/mcp/oauth/register", "POST",
                             {"redirect_uris": [bad]})["status"], 400)
        client = self.registration()
        self.assertTrue(client.startswith("turtleneck-"))
        self.assertEqual(self.app.plugin_clients[client]["redirect_uris"], [CALLBACK])
        self.assertIn(client, self.app.client_file.read_text())
        new = PluginGateway("https://tls.example.test", "actions-client",
                            "x" * 48, ["https://chatgpt.com/aip/g-test/oauth/callback"],
                            self.temp.name, FakeSession)
        self.assertIn(client, new.plugin_clients)

    def test_auth_requires_scope_resource_pkce_and_prevents_replay(self):
        client = self.registration()
        self.assertEqual(self.request("/mcp", "POST", {"jsonrpc": "2.0",
                             "id": 1, "method": "tools/list"})["status"], 401)
        bad = self.request("/mcp/oauth/authorize", query={
            "client_id": client, "redirect_uri": CALLBACK, "response_type": "code",
            "state": "state", "code_challenge": CHALLENGE, "code_challenge_method": "S256",
            "resource": "https://evil.example/mcp",
        })
        self.assertEqual(bad["status"], 400)
        code = self.code(client)
        self.assertEqual(self.exchange(client, code, "x" * 43)["status"], 400)
        valid = self.exchange(client, code)
        self.assertEqual(valid["status"], 200)
        self.assertEqual(self.exchange(client, code)["status"], 400)
        access = valid["body"]["access_token"]
        tools = self.request("/mcp", "POST", {
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
        }, access)
        self.assertEqual(tools["status"], 200)
        self.assertTrue(any(item["name"] == "get_assignments"
                            for item in tools["body"]["result"]["tools"]))
        old_refresh = valid["body"]["refresh_token"]
        refreshed = self.request("/mcp/oauth/token", "POST", {
            "grant_type": "refresh_token", "client_id": client,
            "refresh_token": old_refresh,
        }, form=True)
        self.assertEqual(refreshed["status"], 200)
        self.assertEqual(self.request("/mcp/oauth/token", "POST", {
            "grant_type": "refresh_token", "client_id": client,
            "refresh_token": old_refresh,
        }, form=True)["status"], 400)

    def test_tools_account_isolation_and_invalid_arguments(self):
        client = self.registration()
        alice = self.connect(client, "alice")["access_token"]
        bob = self.connect(client, "bob")["access_token"]
        a = self.call(alice, "get_courses")
        b = self.call(bob, "get_courses")
        self.assertEqual(a["status"], 200)
        self.assertEqual(b["status"], 200)
        self.assertIn("alice", json.dumps(a["body"], ensure_ascii=False))
        self.assertNotIn("bob course", json.dumps(a["body"], ensure_ascii=False))
        self.assertIn("bob", json.dumps(b["body"], ensure_ascii=False))
        self.assertEqual(self.call(alice, "get_assignments",
                                  {"unsubmitted": True})["status"], 200)
        self.assertNotIn("error", self.call(alice, "get_assignments",
                                           {"unsubmitted": True})["body"])
        self.assertIn("error", self.call(alice, "get_assignments",
                                        {"limit": -1})["body"])
        self.assertIn("error", self.call(alice, "unknown_tool")["body"])
        self.assertTrue(self.call(alice, "list_saved_progress",
                                  {"userMessage": "not-list"})["body"]["error"])
        self.assertEqual(self.call(alice, "get_sync_status")["status"], 200)


if __name__ == "__main__":
    unittest.main()
