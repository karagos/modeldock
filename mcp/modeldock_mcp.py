#!/usr/bin/env python3
"""ModelDock MCP server: lets Claude search, evaluate and download AI models
through the ModelDock app. Stdio transport, newline-delimited JSON-RPC 2.0,
Python stdlib only (matching ModelDock's zero-dependency promise).

Register with Claude Code:
  claude mcp add --scope user modeldock -- /usr/bin/python3 /path/to/modeldock_mcp.py
Or in Claude Desktop's claude_desktop_config.json:
  {"mcpServers": {"modeldock": {"command": "/usr/bin/python3",
                                "args": ["/path/to/modeldock_mcp.py"]}}}
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import os
APP = os.environ.get("MODELDOCK_URL", "http://127.0.0.1:8420")
PROTOCOL_FALLBACK = "2025-06-18"
NOT_RUNNING = ("ModelDock is not running. Ask the user to start it by "
               "double-clicking start.command in the modeldock folder, "
               "then retry.")

INSTRUCTIONS = (
    "ModelDock is a local app that downloads AI models from Hugging Face to a "
    "drive the user chose (usually an external SSD). Workflow: use search_models "
    "(several strategies/terms if needed) to find candidates, get_model for "
    "details (file sizes, memory-fit verdicts, license, lineage), system_info "
    "for the Mac's RAM and free disk, then download_model. Sizes are bytes. "
    "The 'fits' field means: green = runs comfortably in memory, orange = tight, "
    "red = will not run on this machine. ALWAYS tell the user the download size "
    "and get their explicit confirmation before calling download_model for "
    "anything over 10 GB. Downloads are checksum-verified and resume-safe.")

TOOLS = [
    {"name": "search_models",
     "description": ("Search Hugging Face for AI models via ModelDock. Matches "
                     "model names AND model card content. Combine filters freely. "
                     "Run multiple calls with different query terms for broad "
                     "needs-based research."),
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "Search words (names, topics, interests)"},
         "type": {"type": "string", "description": "Comma list of: gguf, mlx, image. Default gguf. gguf/mlx are chat LLMs (LM Studio/Ollama and MLX); image is diffusion for ComfyUI"},
         "company": {"type": "string", "description": "Hugging Face author/org, e.g. Qwen, meta-llama, unsloth, bartowski, lmstudio-community"},
         "capability": {"type": "string", "description": "Comma list of: vision, thinking, agentic, coding, moe (chat) or image-gen, video-gen, lora, upscaler (image)"},
         "domain": {"type": "string", "description": "One of: medical, legal, finance, math, science, translation, roleplay"},
         "size": {"type": "string", "description": "Parameter bucket: <=4B, 7-9B, 12-15B, 20-35B, 70B+"},
         "sort": {"type": "string", "description": "downloads (default), trending, newest"},
         "period": {"type": "string", "description": "For downloads sort: 30d (default), all, 6m, 1y"},
         "broaden": {"type": "boolean", "description": "Also search sibling terms (cooking -> culinary, recipe, chef)"}}}},
    {"name": "get_model",
     "description": ("Full details for one model: description, license verdict, "
                     "downloadable variants with exact sizes and memory-fit "
                     "verdicts, whether already in the library, and its base "
                     "model lineage."),
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "required": ["id"], "properties": {
         "id": {"type": "string", "description": "Model id like Qwen/Qwen3-14B-GGUF"},
         "type": {"type": "string", "description": "gguf (default), mlx, or image"}}}},
    {"name": "download_model",
     "description": ("Queue a model variant for download to the user's chosen "
                     "drive. Use the exact variant label from get_model. Tell the "
                     "user the size first and get explicit confirmation for "
                     "anything over 10 GB. Refuses duplicates already in the "
                     "library."),
     "inputSchema": {"type": "object", "required": ["id", "variant_label"], "properties": {
         "id": {"type": "string"},
         "variant_label": {"type": "string", "description": "Exact label of the variant from get_model"},
         "type": {"type": "string", "description": "gguf (default), mlx, or image"}}}},
    {"name": "download_status",
     "description": "Current download queue: states, bytes done/total, errors.",
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "manage_download",
     "description": "Pause, resume or cancel a download by job id (from download_status). Cancel deletes that job's partial files.",
     "inputSchema": {"type": "object", "required": ["action", "job_id"], "properties": {
         "action": {"type": "string", "enum": ["pause", "resume", "cancel"]},
         "job_id": {"type": "string"}}}},
    {"name": "list_library",
     "description": ("Everything downloaded to the current destination drive: "
                     "models with sizes, quantizations, capability hints, "
                     "memory-fit verdicts, plus total used and free disk space."),
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "verify_model",
     "description": ("Re-check a downloaded model against its recorded checksums "
                     "(path from list_library). Big models take a while."),
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "required": ["path"], "properties": {
         "path": {"type": "string", "description": "Model folder path from list_library"}}}},
    {"name": "watchlist",
     "description": "The user's model watchlist: list it, or add/remove a model id.",
     "inputSchema": {"type": "object", "required": ["action"], "properties": {
         "action": {"type": "string", "enum": ["list", "add", "remove"]},
         "model_id": {"type": "string"},
         "type": {"type": "string", "description": "gguf (default), mlx, or image"}}}},
    {"name": "lineage",
     "description": "Family tree of a model: all fine-tunes or quantizations derived from it.",
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "required": ["id"], "properties": {
         "id": {"type": "string", "description": "Base model id, e.g. Qwen/Qwen3-9B"},
         "rel": {"type": "string", "enum": ["finetune", "quantized", "adapter", "merge"],
                 "description": "Relationship, default finetune"}}}},
    {"name": "system_info",
     "description": ("The user's machine and destination: RAM (for judging what "
                     "runs), destination drive, connection state, free space."),
     "annotations": {"readOnlyHint": True},
     "inputSchema": {"type": "object", "properties": {}}},
]


def http(method, path, body=None):
    url = APP + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def prune_card(c):
    out = {"id": c["id"], "type": c.get("mtype"), "downloads_30d": c.get("downloads"),
           "likes": c.get("likes"), "released": (c.get("created") or "")[:10]}
    if c.get("downloads_all") is not None:
        out["downloads_all_time"] = c["downloads_all"]
    if c.get("params"):
        out["params_billion"] = c["params"].get("total_b")
        if c["params"].get("moe"):
            out["moe_active_billion"] = c["params"].get("active_b")
    if c.get("caps"):
        out["capabilities"] = c["caps"]
    if c.get("gated"):
        out["gated"] = True
    if c.get("via_readme"):
        out["matched_in"] = "model card text"
    if c.get("via_term"):
        out["matched_via_sibling_term"] = c["via_term"]
    return out


def call_tool(name, args):
    if name == "search_models":
        qs = {"q": args.get("query", ""), "type": args.get("type", "gguf"),
              "company": args.get("company", ""),
              "capability": args.get("capability", ""),
              "domain": args.get("domain", ""), "size": args.get("size", ""),
              "sort": args.get("sort", "downloads"),
              "period": args.get("period", "30d"),
              "broaden": "1" if args.get("broaden") else "0"}
        res = http("GET", "/api/search?" + urllib.parse.urlencode(qs))
        return {"results": [prune_card(c) for c in res["results"]]}
    if name == "get_model":
        qs = {"id": args["id"], "type": args.get("type", "gguf")}
        m = http("GET", "/api/model?" + urllib.parse.urlencode(qs))
        m.pop("caps", None)
        for v in m.get("variants", []):
            v.pop("files", None)   # internal detail; label is the handle
        return m
    if name == "download_model":
        mtype = args.get("type", "gguf")
        qs = {"id": args["id"], "type": mtype}
        m = http("GET", "/api/model?" + urllib.parse.urlencode(qs))
        variant = next((v for v in m.get("variants", [])
                        if v["label"] == args["variant_label"]), None)
        if variant is None:
            labels = [v["label"] for v in m.get("variants", [])]
            return {"error": "Variant not found. Available: %s" % labels}
        return http("POST", "/api/download", {
            "model_id": args["id"], "variant_label": variant["label"],
            "files": variant["files"] if "files" in variant else [],
            "mtype": mtype, "capability": ""})
    if name == "download_status":
        return http("GET", "/api/downloads")
    if name == "manage_download":
        return http("POST", "/api/downloads/action",
                    {"action": args["action"], "id": args["job_id"]})
    if name == "list_library":
        return http("GET", "/api/library")
    if name == "verify_model":
        return http("POST", "/api/library/verify", {"path": args["path"]})
    if name == "watchlist":
        if args["action"] == "list":
            return http("GET", "/api/watchlist")
        if args["action"] == "add":
            return http("POST", "/api/watchlist",
                        {"id": args["model_id"], "mtype": args.get("type", "gguf")})
        return http("POST", "/api/watchlist/remove", {"id": args["model_id"]})
    if name == "lineage":
        qs = {"id": args["id"], "rel": args.get("rel", "finetune")}
        res = http("GET", "/api/lineage?" + urllib.parse.urlencode(qs))
        return {"results": [prune_card(c) for c in res["results"]]}
    if name == "system_info":
        return http("GET", "/api/system")
    raise ValueError("Unknown tool: %s" % name)


def handle(msg):
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        client_pv = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_FALLBACK
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": client_pv,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "modeldock", "version": "1.0.0"},
            "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            result = call_tool(name, args)
            text = json.dumps(result, indent=1, ensure_ascii=False)
            is_error = isinstance(result, dict) and "error" in result
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": bool(is_error)}}
        except urllib.error.URLError:
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": NOT_RUNNING}], "isError": True}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": "Tool failed: %s" % e}],
                "isError": True}}
    if msg_id is None:
        return None   # notification (e.g. notifications/initialized): no reply
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": "Method not found: %s" % method}}


def main():
    out = sys.stdout.buffer
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            continue
        resp = handle(msg)
        if resp is not None:
            out.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()


if __name__ == "__main__":
    main()
