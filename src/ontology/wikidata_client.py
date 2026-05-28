"""
Wikidata MCP client — spawns the mcp-wikidata server as a subprocess and
communicates via the MCP stdio (JSON-RPC 2.0) protocol.

Usage:
    with WikidataClient() as wd:
        results = wd.search_entity("computing platform")
        meta    = wd.get_metadata("Q170584")
        parents = wd.get_superclasses("Q170584")
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

_MCP_CMD = [
    "uvx",
    "--from",
    "git+https://github.com/esteinholtz-cloudera/mcp-wikidata",
    "mcp-wikidata",
]

# SPARQL to get the immediate superclasses (P279 = subclass of) of an entity.
# Uses rdfs:label directly rather than wikibase:label service to avoid
# Wikidata-specific extensions that require special client handling.
_SUPERCLASS_SPARQL = """
SELECT ?parent ?parentLabel WHERE {{
  wd:{qid} wdt:P279 ?parent .
  ?parent <http://www.w3.org/2000/01/rdf-schema#label> ?parentLabel .
  FILTER(LANG(?parentLabel) = "en")
}}
LIMIT 5
"""


class WikidataClient:
    """MCP stdio client for the mcp-wikidata server."""

    def __init__(self, cmd: Optional[List[str]] = None):
        self._cmd = cmd or _MCP_CMD
        self._proc: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "WikidataClient":
        self._start()
        return self

    def __exit__(self, *_):
        self._stop()

    def _start(self):
        self._proc = subprocess.Popen(
            self._cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        # MCP initialisation handshake
        self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "knowledge-graph-system", "version": "0.1"},
        })
        self._notify("notifications/initialized", {})

    def _stop(self):
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # JSON-RPC transport
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        with self._lock:
            self._req_id += 1
            return self._req_id

    def _send(self, msg: Dict[str, Any]):
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def _recv(self) -> Dict[str, Any]:
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed connection unexpectedly")
            line = line.strip()
            if not line:
                continue
            return json.loads(line)

    def _call(self, method: str, params: Dict[str, Any]) -> Any:
        req_id = self._next_id()
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        while True:
            msg = self._recv()
            # Ignore server-initiated notifications
            if "id" not in msg:
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg.get("result")

    def _notify(self, method: str, params: Dict[str, Any]):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _tool_call(self, tool: str, arguments: Dict[str, Any]) -> str:
        result = self._call("tools/call", {"name": tool, "arguments": arguments})
        if isinstance(result, dict):
            if result.get("isError"):
                content = result.get("content", [])
                msg = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
                raise RuntimeError(msg or "tool returned isError")
            content = result.get("content", [])
            if isinstance(content, list):
                return "\n".join(
                    c.get("text", "") for c in content if c.get("type") == "text"
                )
            return str(result)
        return str(result)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_entity(self, query: str) -> List[Dict[str, str]]:
        """
        Search for Wikidata entities matching `query`.
        Returns list of {"qid", "label", "description"}.
        """
        import re
        raw = self._tool_call("search_entity", {"query": query})

        # Try JSON first, then fall back to regex extraction of Q-numbers.
        # The MCP server may return JSON, comma/newline separated strings,
        # or concatenated QIDs like "Q1234Q5678".
        qids: List[str] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                qids = [str(q).strip() for q in parsed if str(q).strip()]
            elif isinstance(parsed, str):
                qids = [parsed.strip()]
        except (json.JSONDecodeError, TypeError):
            pass

        if not qids:
            qids = re.findall(r'Q\d+', raw)

        qids = qids[:5]
        # Batch-fetch labels+descriptions in one SPARQL call rather than one
        # get_metadata call per QID — avoids repeated API calls that trigger 403s.
        labels = self._batch_labels(qids)

        results = []
        for qid in qids:
            if qid in labels:
                results.append({"qid": qid, **labels[qid]})
            else:
                # SPARQL batch failed for this QID; fall back to get_metadata
                try:
                    meta = self.get_metadata(qid)
                    results.append({"qid": qid, "label": meta["label"], "description": meta["description"]})
                except Exception:
                    results.append({"qid": qid, "label": qid, "description": ""})
        return results

    @staticmethod
    def _parse_sparql_rows(raw: str) -> List[Dict]:
        """Parse a SPARQL result that may be a JSON array or concatenated JSON objects.

        FastMCP serialises list-of-dict tool results as multiple MCP text content
        blocks, which _tool_call joins with newlines. The result is a sequence of
        multi-line JSON objects — neither a JSON array nor strict NDJSON.
        json.JSONDecoder.raw_decode handles this by finding each object boundary.
        """
        raw = raw.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            pass
        decoder = json.JSONDecoder()
        rows, idx = [], 0
        while idx < len(raw):
            while idx < len(raw) and raw[idx] in " \t\n\r":
                idx += 1
            if idx >= len(raw):
                break
            try:
                obj, idx = decoder.raw_decode(raw, idx)
                if isinstance(obj, dict):
                    rows.append(obj)
            except json.JSONDecodeError:
                break
        return rows

    def _batch_labels(self, qids: List[str]) -> Dict[str, Dict[str, str]]:
        """Fetch English labels and descriptions for multiple QIDs in one SPARQL call.

        Uses rdfs:label directly rather than the wikibase:label service to avoid
        dependency on Wikidata-specific extensions that can be unreliable.
        """
        if not qids:
            return {}
        values = " ".join(f"wd:{q}" for q in qids)
        sparql = (
            "SELECT ?item ?label ?desc WHERE { "
            f"VALUES ?item {{ {values} }} "
            "?item <http://www.w3.org/2000/01/rdf-schema#label> ?label . "
            "FILTER(LANG(?label) = \"en\") "
            "OPTIONAL { ?item <https://schema.org/description> ?desc . FILTER(LANG(?desc) = \"en\") } "
            "}"
        )
        try:
            raw = self._tool_call("execute_sparql", {"sparql_query": sparql})
            rows = self._parse_sparql_rows(raw)
        except Exception:
            return {}

        results: Dict[str, Dict[str, str]] = {}
        for row in rows:
            uri = (row.get("item") or {}).get("value", "")
            qid = uri.split("/")[-1] if "/" in uri else ""
            label = (row.get("label") or {}).get("value", "")
            desc = (row.get("desc") or {}).get("value", "")
            if qid and label:
                results[qid] = {"label": label, "description": desc}
        return results

    def get_metadata(self, entity_id: str) -> Dict[str, str]:
        """Return {"label", "description"} for a Wikidata entity ID."""
        raw = self._tool_call("get_metadata", {"entity_id": entity_id, "language": "en"})
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                label = (data.get("label") or "").strip()
                desc = (data.get("description") or "").strip()
                if label:
                    return {"label": label, "description": desc}
        except (json.JSONDecodeError, TypeError):
            pass
        return {"label": entity_id, "description": ""}

    def get_superclasses(self, qid: str) -> List[Dict[str, str]]:
        """
        Return immediate superclasses of `qid` via P279.
        Result: list of {"qid", "label"}.
        """
        sparql = _SUPERCLASS_SPARQL.format(qid=qid)
        try:
            raw = self._tool_call("execute_sparql", {"sparql_query": sparql})
            rows = self._parse_sparql_rows(raw)
        except Exception:
            return []
        results = []
        for row in rows:
            parent_uri = (row.get("parent") or {}).get("value", "")
            label = (row.get("parentLabel") or {}).get("value", "")
            qid_part = parent_uri.split("/")[-1] if "/" in parent_uri else parent_uri
            if qid_part:
                results.append({"qid": qid_part, "label": label or qid_part})
        return results


def wikidata_search(query: str, cmd: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Convenience function: search Wikidata and return results, managing client lifecycle."""
    with WikidataClient(cmd=cmd) as wd:
        return wd.search_entity(query)


def wikidata_superclasses(qid: str, cmd: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Convenience function: get P279 superclasses for a QID."""
    with WikidataClient(cmd=cmd) as wd:
        return wd.get_superclasses(qid)
