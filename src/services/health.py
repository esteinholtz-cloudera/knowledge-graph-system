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

        # Subagent provider has no HTTP endpoint — check the CLI + auth instead.
        if llm.provider == "subagent":
            return self._check_subagent(llm)

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

    def _check_subagent(self, llm) -> PrecheckResult:
        """Preflight for the subagent provider: CLI present and authenticated."""
        import shutil
        import subprocess

        checks: List[Dict[str, Any]] = []
        cli = llm.subagent_cli

        if not shutil.which(cli) and "/" not in cli:
            checks.append({
                "name": "subagent_cli",
                "ok": False,
                "message": f"{cli!r} not found on PATH",
                "hint": "install the Cursor CLI or set llm.subagent_cli in config.yaml",
            })
            return PrecheckResult(ok=False, checks=checks)

        try:
            result = subprocess.run(
                [cli, "status"], capture_output=True, text=True, timeout=15
            )
            authed = result.returncode == 0
            checks.append({
                "name": "subagent_auth",
                "ok": authed,
                "message": (result.stdout or result.stderr or "").strip()
                or ("authenticated" if authed else "not authenticated"),
                **({} if authed else {"hint": f"run `{cli} login`"}),
            })
        except Exception as e:  # noqa: BLE001 — surface any CLI failure to the user
            checks.append({
                "name": "subagent_auth",
                "ok": False,
                "message": str(e),
            })
            return PrecheckResult(ok=False, checks=checks)

        checks.append({
            "name": "llm_model",
            "ok": True,
            "message": llm.model or "subagent default",
        })
        return PrecheckResult(ok=all(c["ok"] for c in checks), checks=checks)
