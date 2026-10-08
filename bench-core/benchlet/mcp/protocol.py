"""의존성 없는 MCP stdio 서버 골격 (JSON-RPC 2.0, 프로토콜 2024-11-05).

Content-Length 헤더 없이 줄 단위 JSON(newline-delimited)을 쓴다. Claude Code 의 stdio 전송이 이 형식이다.
initialize · notifications/initialized · ping · tools/list · tools/call 만 구현한다. 이 머신의 python3 이 3.9 라 공식 SDK 를 쓰지 않는다.
"""
from __future__ import annotations

import json
import sys
import traceback

PROTOCOL_VERSION = "2024-11-05"


class Tool:
    def __init__(self, name: str, description: str, schema: dict, fn):
        self.name, self.description, self.schema, self.fn = name, description, schema, fn


class Server:
    def __init__(self, name: str, version: str):
        self.name, self.version = name, version
        self.tools: dict = {}

    def tool(self, name: str, description: str, schema: dict):
        def deco(fn):
            self.tools[name] = Tool(name, description, schema, fn)
            return fn
        return deco

    # ── 디스패치 ──────────────────────────────────────────────────────────
    def handle(self, msg: dict):
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            return self._result(mid, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                                      "serverInfo": {"name": self.name, "version": self.version}})
        if method == "notifications/initialized" or method == "notifications/cancelled":
            return None
        if method == "ping":
            return self._result(mid, {})
        if method == "tools/list":
            return self._result(mid, {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.schema}
                                                for t in self.tools.values()]})
        if method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            t = self.tools.get(name)
            if not t:
                return self._error(mid, -32601, f"unknown tool {name}")
            try:
                out = t.fn(**args)
            except ToolError as e:
                return self._result(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
            except Exception as e:                       # noqa: BLE001
                return self._result(mid, {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}"}], "isError": True})
            if isinstance(out, str):
                content = [{"type": "text", "text": out}]
                return self._result(mid, {"content": content})
            return self._result(mid, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}],
                                      "structuredContent": out})
        if mid is None:
            return None
        return self._error(mid, -32601, f"unknown method {method}")

    @staticmethod
    def _result(mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _error(mid, code, message):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    def serve(self, inp=None, out=None):
        inp = inp or sys.stdin
        out = out or sys.stdout
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(msg)
            if resp is not None:
                out.write(json.dumps(resp, ensure_ascii=False) + "\n")
                out.flush()


class ToolError(Exception):
    """사용자에게 보이는 실패. isError 로 돌아간다."""
