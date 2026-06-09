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


def read_repo(repo: str, path: str, token: str, branch: str = "main", max_chars: int = 6000) -> str:
    """Read a file, or list a directory, in ``repo`` — so Bentlyk can see its own workshop."""

    if not token:
        return "(no GitHub token configured)"
    base = f"{_API}/repos/{repo}/contents/{path.lstrip('/')}"
    status, cur = _req("GET", f"{base}?ref={branch}", token)
    if status != 200:
        return f"(can't read {repo}/{path}: {status} {cur.get('message', '')})"
    if isinstance(cur, list):  # a directory listing
        names = [f"{e.get('type', '?')[:3]}  {e.get('path', '')}" for e in cur]
        return f"{repo}/{path or '.'} contains:\n" + "\n".join(sorted(names))
    if cur.get("encoding") == "base64" and cur.get("content"):
        try:
            text = base64.b64decode(cur["content"]).decode(errors="replace")
        except Exception:  # pragma: no cover
            return "(could not decode file)"
        return text[:max_chars]
    return f"(nothing readable at {repo}/{path})"
