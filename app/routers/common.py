import json
from typing import Any

from fastapi import Response


def stored_json_response(status: int, body: dict[str, Any]) -> Response:
    """Serialize an idempotent response with sorted keys.

    jsonb does not preserve key order, so sorting makes a fresh response and a replay
    byte-identical.
    """
    return Response(
        content=json.dumps(body, sort_keys=True, separators=(",", ":")),
        status_code=status,
        media_type="application/json",
    )
