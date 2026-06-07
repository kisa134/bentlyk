"""Minimal GitHub commit client (standard library only).

Lets Bentlyk write files into its own repo ("home") via the REST API using a
fine-grained token, so it can author and publish code/pages. Scoped to whatever
the token allows — keep it to the self-repo, never the core repo.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request

_API = "https://api.github.com"


def _req(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bentlyk",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "{}")
        except Exception:  # pragma: no cover
            return exc.code, {}
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network
        return 0, {"message": str(exc)}


def commit_file(
    repo: str, path: str, text: str, message: str, token: str, branch: str = "main"
) -> str:
    """Create or update a file in ``repo`` at ``path``. Returns a status string."""

    if not token:
        return "(no GitHub token configured)"
    base = f"{_API}/repos/{repo}/contents/{path.lstrip('/')}"
    # Look up existing sha (required to update an existing file).
    status, cur = _req("GET", f"{base}?ref={branch}", token)
    sha = cur.get("sha") if status == 200 else None
    body = {
        "message": message,
        "content": base64.b64encode(text.encode()).decode(),
        "branch": branch,
    }
    if sha:
        body["sha"] = sha
    status, resp = _req("PUT", base, token, body)
    if status in (200, 201):
        commit = (resp.get("commit") or {}).get("html_url", "")
        return f"committed {path} to {repo}@{branch} {commit}".strip()
    return f"(commit failed {status}: {resp.get('message', '')})"
