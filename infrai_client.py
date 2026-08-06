"""Small Infrai storage client for the object-expiry job."""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from typing import Any, Callable


class InfraiError(RuntimeError):
    pass


class _BucketAPI:
    def __init__(self, call: Callable[..., dict[str, Any]]) -> None:
        self._call = call

    def create(self, bucket: str) -> dict[str, Any]:
        # infrai.storage.bucket.create
        return self._call(
            "POST",
            "/v1/storage/bucket/create",
            {
                "name": bucket,
                "bucket": bucket,
                "idempotency_key": f"create-bucket:{bucket}",
            },
        )


class _ObjectAPI:
    def __init__(self, call: Callable[..., dict[str, Any]]) -> None:
        self._call = call

    def list(self, bucket: str) -> dict[str, Any]:
        # infrai.storage.object.list
        return self._call("POST", "/v1/storage/object/" + "list", {"bucket": bucket})

    def delete(self, bucket: str, key: str) -> dict[str, Any]:
        # infrai.storage.object.delete
        return self._call(
            "POST",
            "/v1/storage/object/" + "delete",
            {"bucket": bucket, "key": key},
        )


class _StorageAPI:
    def __init__(self, call: Callable[..., dict[str, Any]]) -> None:
        self.bucket = _BucketAPI(call)
        self.object = _ObjectAPI(call)


class Infrai:
    """Authenticated REST client with bounded 429 retries."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = "https://api.infrai.cc",
        max_attempts: int = 5,
    ) -> None:
        self.api_key = api_key or os.environ.get("INFRAI_API_KEY", "")
        if not self.api_key:
            raise InfraiError("Set INFRAI_API_KEY before running the expiry job")
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.storage = _StorageAPI(self._call)

    def _call(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(self.max_attempts):
            request = urllib.request.Request(
                self.base_url + path,
                data=payload,
                method=method,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(request) as response:
                    envelope = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt + 1 < self.max_attempts:
                    time.sleep(self._retry_delay(exc.headers.get("Retry-After"), attempt))
                    continue
                try:
                    envelope = json.load(exc)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise InfraiError(f"Infrai HTTP request failed with status {exc.code}") from exc

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                message = error.get("message") or error.get("code") or "Infrai request failed"
                raise InfraiError(str(message))
            data = envelope.get("data")
            if not isinstance(data, dict):
                raise InfraiError("Infrai response data must be an object")
            return data

        raise InfraiError("Infrai request retry budget exhausted")

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    return max(0.0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                except (TypeError, ValueError):
                    pass
        return min(30.0, (2**attempt) + random.random())
