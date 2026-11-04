from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx


class BabyBuddyError(RuntimeError):
    pass


def _is_loopback_url(url: str) -> bool:
    hostname = urlparse(url).hostname
    if hostname == "localhost":
        return True
    if hostname is None:
        return False
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class BabyBuddyConfig:
    base_url: str
    token: str
    child_id: int
    bottle_type: str = "breast milk"
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("Baby Buddy URL is required")
        if not self.token.strip():
            raise ValueError("Baby Buddy token is required")
        if self.child_id <= 0:
            raise ValueError("Baby Buddy child ID must be positive")
        if self.bottle_type not in {
            "breast milk",
            "formula",
            "fortified breast milk",
        }:
            raise ValueError("unsupported bottle type")


class BabyBuddyClient:
    def __init__(
        self,
        config: BabyBuddyConfig,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.config = config
        self._transport = transport
        self._trust_env = not _is_loopback_url(config.base_url)

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Token {self.config.token}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, object]] = None,
        allow_statuses: tuple[int, ...] = (),
    ) -> Optional[object]:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            with httpx.Client(
                timeout=self.config.timeout_seconds,
                transport=self._transport,
                trust_env=self._trust_env,
            ) as client:
                response = client.request(
                    method, url, headers=self._headers, json=json
                )
        except httpx.HTTPError as exc:
            raise BabyBuddyError(f"Baby Buddy connection failed: {exc}") from exc
        if response.status_code in allow_statuses:
            return None
        if response.status_code >= 400:
            detail = response.text.replace(self.config.token, "[redacted]")[:300]
            raise BabyBuddyError(
                f"Baby Buddy {method} {path} failed: "
                f"HTTP {response.status_code} {detail}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def check(self) -> Dict[str, object]:
        result = self._request("GET", "/api/children/?limit=1000")
        if not isinstance(result, dict):
            raise BabyBuddyError("Baby Buddy returned an invalid children response")
        children = result.get("results", [])
        child = next(
            (
                item
                for item in children
                if isinstance(item, dict)
                and "id" in item
                and int(item["id"]) == self.config.child_id
            ),
            None,
        )
        return {
            "connected": True,
            "child_found": child is not None,
            "child_id": self.config.child_id,
            "child": (
                {
                    "first_name": str(child.get("first_name", "")).strip(),
                    "last_name": str(child.get("last_name", "")).strip(),
                    "birth_date": child.get("birth_date"),
                }
                if child is not None
                else None
            ),
        }

    def create_event(self, payload: Dict[str, object]) -> Dict[str, object]:
        result = self._request("POST", "/api/babytap/events/", json=payload)
        if not isinstance(result, dict) or "event_id" not in result:
            raise BabyBuddyError("BabyTap event response has no event_id")
        return result

    def delete_event(self, event_id: str) -> None:
        self._request(
            "DELETE",
            f"/api/babytap/events/{event_id}/",
            allow_statuses=(404,),
        )
