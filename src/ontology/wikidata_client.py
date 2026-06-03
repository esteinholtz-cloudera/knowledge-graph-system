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
import logging
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_QID_RE = re.compile(r"Q\d+", re.IGNORECASE)
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
_USER_AGENT = (
    "KnowledgeGraphSystem/0.1 "
    "(https://github.com/esteinholtz-cloudera/knowledge-graph-system; ontology-review)"
)


def _escape_sparql_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _sparql_json_query(sparql: str, retries: int = 3) -> List[Dict[str, Any]]:
    """Run SPARQL on query.wikidata.org; return bindings as {var: {value: ...}} rows."""
    data = urllib.parse.urlencode({"query": sparql}).encode()
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(
            _WIKIDATA_SPARQL,
            data=data,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                parsed = json.loads(resp.read().decode())
            return parsed.get("results", {}).get("bindings", [])
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.0)
                continue
            raise
    if last_err:
        raise last_err
    return []


def _wikidata_api_get(params: Dict[str, str], retries: int = 3) -> Dict[str, Any]:
    params = {**params, "format": "json"}
    url = f"{_WIKIDATA_API}?{urllib.parse.urlencode(params)}"
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.0)
                continue
            raise
    if last_err:
        raise last_err
    return {}


def _qid_from_value(value: Any) -> str:
    """Extract a Wikidata QID from a string or URI."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        text = text.rsplit("/", 1)[-1]
    match = _QID_RE.search(text)
    return match.group(0).upper() if match else ""


def _normalize_entity_hit(item: Any) -> Optional[Dict[str, str]]:
    """Normalize MCP / API shapes to {qid, label, description}."""
    if isinstance(item, str):
        qid = _qid_from_value(item)
        if not qid:
            return None
        return {"qid": qid, "label": "", "description": ""}
    if not isinstance(item, dict):
        return None
    qid = _qid_from_value(
        item.get("qid")
        or item.get("id")
        or item.get("entity_id")
        or item.get("entity")
        or item.get("uri")
    )
    if not qid:
        return None
    label = str(
        item.get("label")
        or item.get("title")
        or item.get("name")
        or item.get("entity_label")
        or ""
    ).strip()
    desc = str(item.get("description") or item.get("desc") or "").strip()
    return {"qid": qid, "label": label, "description": desc}

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

    def _search_via_mcp(self, query: str) -> List[Dict[str, str]]:
        raw = self._tool_call("search_entity", {"query": query})
        hits: List[Dict[str, str]] = []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                hit = _normalize_entity_hit(parsed)
                if hit:
                    hits.append(hit)
            elif isinstance(parsed, list):
                for item in parsed:
                    hit = _normalize_entity_hit(item)
                    if hit:
                        hits.append(hit)
            elif isinstance(parsed, str):
                qid = _qid_from_value(parsed)
                if qid:
                    hits.append({"qid": qid, "label": "", "description": ""})
        except (json.JSONDecodeError, TypeError):
            pass
        if not hits:
            for qid in _QID_RE.findall(raw)[:5]:
                hits.append({"qid": qid.upper(), "label": "", "description": ""})
        return hits

    @staticmethod
    def _search_via_wb_api(query: str) -> List[Dict[str, str]]:
        data = _wikidata_api_get({
            "action": "wbsearchentities",
            "search": query,
            "language": "en",
            "type": "item",
            "limit": "5",
        })
        hits = []
        for item in data.get("search", []):
            qid = item.get("id", "")
            if qid.startswith("Q"):
                hits.append({
                    "qid": qid,
                    "label": item.get("label", qid),
                    "description": item.get("description", ""),
                })
        return hits

    @staticmethod
    def _search_via_sparql(query: str) -> List[Dict[str, str]]:
        """EntitySearch via Wikidata Query Service (separate rate limit from www API)."""
        escaped = _escape_sparql_literal(query)
        sparql = f"""
SELECT ?item ?itemLabel ?itemDescription WHERE {{
  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:endpoint "www.wikidata.org" ;
                     wikibase:api "EntitySearch" ;
                     mwapi:search "{escaped}" ;
                     mwapi:language "en" .
    ?item wikibase:apiOutputItem mwapi:item .
    ?itemLabel wikibase:apiLabel true .
    ?itemDescription wikibase:apiDescription true .
  }}
}} LIMIT 5
"""
        hits = []
        for row in _sparql_json_query(sparql):
            uri = (row.get("item") or {}).get("value", "")
            qid = _qid_from_value(uri)
            if not qid:
                continue
            label = (row.get("itemLabel") or {}).get("value", qid)
            desc = (row.get("itemDescription") or {}).get("value", "")
            hits.append({"qid": qid, "label": label, "description": desc})
        return hits

    def search_entity(self, query: str) -> List[Dict[str, str]]:
        """
        Search for Wikidata entities matching `query`.
        Returns list of {"qid", "label", "description"}.
        Tries MCP, then wbsearchentities API, then Query Service EntitySearch.
        """
        errors: List[str] = []
        for name, fn in (
            ("MCP", lambda: self._search_via_mcp(query)),
            ("API", lambda: self._search_via_wb_api(query)),
            ("SPARQL", lambda: self._search_via_sparql(query)),
        ):
            try:
                hits = fn()
                if hits:
                    enriched = self._enrich_labels(hits[:5])
                    return enriched
            except Exception as e:
                msg = f"{name}: {e}"
                errors.append(msg)
                logger.warning("Wikidata search %s failed: %s", name, e)
        if errors:
            logger.warning("Wikidata search exhausted for %r: %s", query, "; ".join(errors))
        return []

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

    @staticmethod
    def _labels_via_wikidata_api(qids: List[str]) -> Dict[str, Dict[str, str]]:
        """Fetch English labels via the public Wikidata API (no MCP)."""
        if not qids:
            return {}
        try:
            data = _wikidata_api_get({
                "action": "wbgetentities",
                "ids": "|".join(qids[:50]),
                "props": "labels|descriptions",
                "languages": "en",
            })
        except Exception:
            return {}

        out: Dict[str, Dict[str, str]] = {}
        for qid, ent in (data.get("entities") or {}).items():
            if not qid.startswith("Q"):
                continue
            label = ((ent.get("labels") or {}).get("en") or {}).get("value", "")
            desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value", "")
            if label:
                out[qid] = {"label": label, "description": desc}
        return out

    def _enrich_labels(self, hits: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Fill missing labels/descriptions using API, SPARQL, then get_metadata."""
        if not hits:
            return hits
        need = [
            h["qid"]
            for h in hits
            if not (h.get("label") or "").strip() or h.get("label") == h["qid"]
        ]
        if not need:
            return hits

        merged: Dict[str, Dict[str, str]] = {}
        merged.update(self._labels_via_wikidata_api(need))
        still = [q for q in need if q not in merged]
        if still:
            merged.update(self._batch_labels(still))
        still = [q for q in need if q not in merged or not merged[q].get("label")]
        for qid in still:
            try:
                meta = self.get_metadata(qid)
                if meta.get("label") and meta["label"] != qid:
                    merged[qid] = meta
            except Exception:
                continue

        for hit in hits:
            extra = merged.get(hit["qid"])
            if not extra:
                continue
            if extra.get("label"):
                hit["label"] = extra["label"]
            if extra.get("description"):
                hit["description"] = extra["description"]
            elif not hit.get("description"):
                hit["description"] = extra.get("description", "")
        return hits

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

    def _superclasses_via_direct_sparql(self, qid: str) -> List[Dict[str, str]]:
        sparql = _SUPERCLASS_SPARQL.format(qid=qid)
        results = []
        for row in _sparql_json_query(sparql):
            parent_uri = (row.get("parent") or {}).get("value", "")
            label = (row.get("parentLabel") or {}).get("value", "")
            qid_part = _qid_from_value(parent_uri)
            if qid_part:
                results.append({
                    "qid": qid_part,
                    "label": label.strip() if label else "",
                    "description": "",
                })
        return results

    def get_superclasses(self, qid: str) -> List[Dict[str, str]]:
        """
        Return immediate superclasses of `qid` via P279.
        Result: list of {"qid", "label"}.
        """
        sparql = _SUPERCLASS_SPARQL.format(qid=qid)
        rows: List[Dict] = []
        try:
            raw = self._tool_call("execute_sparql", {"sparql_query": sparql})
            rows = self._parse_sparql_rows(raw)
        except Exception as e:
            logger.warning("MCP P279 lookup failed for %s: %s", qid, e)
            try:
                return self._enrich_labels(self._superclasses_via_direct_sparql(qid))
            except Exception as e2:
                logger.warning("Direct SPARQL P279 failed for %s: %s", qid, e2)
                return []
        results = []
        for row in rows:
            parent_uri = (row.get("parent") or {}).get("value", "")
            label = (row.get("parentLabel") or {}).get("value", "")
            qid_part = _qid_from_value(parent_uri)
            if qid_part:
                results.append({
                    "qid": qid_part,
                    "label": label.strip() if label else "",
                    "description": "",
                })
        if not results:
            try:
                results = self._superclasses_via_direct_sparql(qid)
            except Exception:
                pass
        return self._enrich_labels(results)

    def get_p279_chain(self, qid: str, max_depth: int = 12) -> List[Dict[str, str]]:
        """Walk P279 recursively from `qid` toward root.

        Returns ordered list [entity, parent, grandparent, …] (leaf first).
        Stops at max_depth, cycles, or when no P279 parents exist.
        When multiple parents exist, picks the first with a non-empty label.
        """
        start = _qid_from_value(qid)
        if not start:
            return []

        meta = self.get_metadata(start)
        chain: List[Dict[str, str]] = [{
            "qid": start,
            "label": meta.get("label") or start,
            "description": meta.get("description", ""),
        }]
        visited = {start}
        current = start

        for _ in range(max_depth):
            parents = self.get_superclasses(current)
            if not parents:
                break
            parent = next((p for p in parents if p.get("label")), parents[0])
            pqid = _qid_from_value(parent.get("qid", ""))
            if not pqid or pqid in visited:
                break
            visited.add(pqid)
            chain.append({
                "qid": pqid,
                "label": parent.get("label") or pqid,
                "description": parent.get("description", ""),
            })
            current = pqid

        return chain


def wikidata_search(query: str, cmd: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Convenience function: search Wikidata and return results, managing client lifecycle."""
    with WikidataClient(cmd=cmd) as wd:
        return wd.search_entity(query)


def wikidata_superclasses(qid: str, cmd: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Convenience function: get P279 superclasses for a QID."""
    with WikidataClient(cmd=cmd) as wd:
        return wd.get_superclasses(qid)


def wikidata_p279_chain(qid: str, max_depth: int = 12, cmd: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Convenience: recursive P279 chain from entity toward root."""
    with WikidataClient(cmd=cmd) as wd:
        return wd.get_p279_chain(qid, max_depth=max_depth)
