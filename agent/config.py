"""Settings desde entorno. Sin secretos en archivos: todo por env.

Variables:
  ZABBIX_URL    Endpoint JSON-RPC del lab (ej. http://localhost/api_jsonrpc.php)
  ZABBIX_TOKEN  API token (Bearer). Vacio = sin token.
  ZABBIX_USER / ZABBIX_PASSWORD  Solo lab local via user.login (env del shell).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


class Settings(BaseModel):
    zabbix_url: str = Field(default="http://localhost/api_jsonrpc.php")
    zabbix_token: str = Field(default="")
    zabbix_user: str = Field(default="")
    zabbix_password: str = Field(default="")
    timeout: float = Field(default=15.0)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            zabbix_url=os.getenv("ZABBIX_URL", "http://localhost/api_jsonrpc.php"),
            zabbix_token=os.getenv("ZABBIX_TOKEN", ""),
            zabbix_user=os.getenv("ZABBIX_USER", ""),
            zabbix_password=os.getenv("ZABBIX_PASSWORD", ""),
            timeout=float(os.getenv("ZABBIX_TIMEOUT", "15")),
        )
