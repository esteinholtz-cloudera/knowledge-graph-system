"""LLM and embedding preflight checks."""
from typing import Any, Dict, List

from src.config.settings import load_config
from src.services.models import PrecheckResult


class HealthService:
    def check(self) -> PrecheckResult:
        import httpx

        app = load_config()
        llm = app.llm
        res = app.entity_resolution
        base_url = llm.resolved_base_url()
        checks: List[Dict[str, Any]] = []
        all_ok = True

        headers: Dict[str, str] = {}
        if llm.get_api_key():
            headers["Authorization"] = f"Bearer {llm.get_api_key()}"

        # LLM endpoint
        try:
            resp = httpx.get(f"{base_url}/models", headers=headers, timeout=8)
            resp.raise_for_status()
            available = [m["id"] for m in resp.json().get("data", [])]
            if llm.model is None:
                if available:
                    checks.append({
                        "name": "llm_model",
                        "ok": True,
                        "message": f"{available[0]} (auto-detected)",
                    })
                else:
                    checks.append({
                        "name": "llm_model",
                        "ok": False,
                        "message": f"no models available at {base_url}",
                    })
                    all_ok = False
            elif llm.model in available:
                checks.append({
                    "name": "llm_model",
                    "ok": True,
                    "message": llm.model,
                })
            else:
                checks.append({
                    "name": "llm_model",
                    "ok": False,
                    "message": f"{llm.model!r} NOT found at {base_url}",
                    "available": available,
                })
                all_ok = False
        except Exception as e:
            checks.append({
                "name": "llm_endpoint",
                "ok": False,
                "message": f"{base_url} unreachable ({e})",
            })
            all_ok = False

        # Embedding model
        if res.enabled and "embedding" in res.strategies:
            try:
                resp = httpx.get(f"{base_url}/models", headers=headers, timeout=8)
                available = [m["id"] for m in resp.json().get("data", [])]
                if res.embedding_model in available:
                    checks.append({
                        "name": "embed_model",
                        "ok": True,
                        "message": res.embedding_model,
                    })
                else:
                    checks.append({
                        "name": "embed_model",
                        "ok": False,
                        "message": f"{res.embedding_model!r} NOT found",
                        "available": available,
                        "hint": "load it in LM Studio or update embedding_model in config.yaml",
                    })
                    all_ok = False
            except Exception as e:
                checks.append({
                    "name": "embed_model",
                    "ok": False,
                    "message": str(e),
                })
                all_ok = False
        elif res.enabled:
            checks.append({
                "name": "embed_model",
                "ok": True,
                "skipped": True,
                "message": f"not used — strategies: {res.strategies}",
            })

        # Resolution summary
        if res.enabled:
            checks.append({
                "name": "resolution",
                "ok": True,
                "message": f"enabled ({', '.join(res.strategies)}, threshold={res.embedding_threshold})",
            })
        else:
            checks.append({
                "name": "resolution",
                "ok": True,
                "skipped": True,
                "message": "disabled",
            })

        return PrecheckResult(ok=all_ok, checks=checks)
