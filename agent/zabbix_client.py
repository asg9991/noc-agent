"""Wrapper minimo sobre Zabbix JSON-RPC (solo lectura en este esqueleto)."""

from __future__ import annotations

from typing import Any

import httpx


class ZabbixClient:
    def __init__(
        self,
        url: str,
        token: str = "",
        user: str = "",
        password: str = "",
        timeout: float = 15.0,
    ) -> None:
        self.url = url
        self.token = token
        self.user = user
        self.password = password
        self.timeout = timeout
        self._auth: str | None = None

    def _headers(self) -> dict[str, str]:
        # Zabbix >= 7 rechaza el campo "auth" top-level: tanto el API token
        # como la sesion de user.login viajan como Bearer header.
        headers = {"Content-Type": "application/json"}
        bearer = self.token or self._auth
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return headers

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": 1,
        }
        with httpx.Client(timeout=self.timeout) as http:
            resp = http.post(self.url, json=payload, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Zabbix API error: {data['error']}")
        return data.get("result")

    def _ensure_login(self) -> None:
        if self.token or self._auth or not (self.user and self.password):
            return
        payload = {
            "jsonrpc": "2.0",
            "method": "user.login",
            "params": {"username": self.user, "password": self.password},
            "id": 1,
        }
        with httpx.Client(timeout=self.timeout) as http:
            resp = http.post(
                self.url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Zabbix login error: {data['error']}")
        self._auth = data.get("result")

    def get_version(self) -> str:
        return str(self._call("apiinfo.version"))

    def get_problems(self, limit: int = 20) -> list[dict[str, Any]]:
        self._ensure_login()
        result = self._call(
            "problem.get",
            {
                "output": ["eventid", "name", "severity", "clock", "objectid"],
                "recent": True,
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": limit,
            },
        )
        return list(result or [])

    def get_hosts(self, limit: int = 20) -> list[dict[str, Any]]:
        self._ensure_login()
        result = self._call(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status"],
                "sortfield": ["host"],
                "limit": limit,
            },
        )
        return list(result or [])
