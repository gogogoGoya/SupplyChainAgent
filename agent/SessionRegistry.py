from pathlib import Path
from typing import Dict, List, Callable, Any, Optional
import json
# ============================================================
# Session 注册器
# ============================================================

class SessionRegistry:
    """
    管理企业 + 角色级 session_id
    结构：
    {
        "enterprise_A": {
            "Analyst": "session_xxx",
            "HR": "session_yyy",
            ...
        },
        ...
    }
    """

    def __init__(self, persist_path: Optional[Path] = None):
        self.persist_path = persist_path
        self.sessions: Dict[str, Dict[str, str]] = {}
        self._load()

    def _load(self):
        if self.persist_path and self.persist_path.exists():
            try:
                self.sessions = json.loads(self.persist_path.read_text(encoding="utf-8"))
            except Exception:
                self.sessions = {}

    def save(self):
        if self.persist_path:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(
                json.dumps(self.sessions, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

    def get(self, enterprise_id: str, role: str) -> str:
        return self.sessions.get(enterprise_id, {}).get(role, "")

    def set(self, enterprise_id: str, role: str, session_id: str):
        self.sessions.setdefault(enterprise_id, {})[role] = session_id
        self.save()

    def clear(self, enterprise_id: str, role: str):
        role_sessions = self.sessions.get(enterprise_id)
        if not role_sessions:
            return

        role_sessions.pop(role, None)
        if not role_sessions:
            self.sessions.pop(enterprise_id, None)
        self.save()
