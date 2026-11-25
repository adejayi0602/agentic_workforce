"""Enumerate every API route with its full path.

Recent FastAPI versions keep included routers as lazy wrappers, so `app.routes` alone does not
list the endpoints. Security tests rely on seeing every route, so this walks the tree itself.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    route: APIRoute


def iter_api_routes(app: FastAPI) -> list[RouteInfo]:
    found = sorted(_walk(app.routes, ""), key=lambda r: (r.path, r.method))
    if not found:
        raise RuntimeError("No API routes found: the route walker no longer matches FastAPI.")
    return found


def _walk(routes: Sequence[Any], prefix: str) -> Iterator[RouteInfo]:
    for node in routes:
        if isinstance(node, APIRoute):
            for method in sorted(node.methods or ()):
                yield RouteInfo(method=method, path=prefix + node.path, route=node)
        elif hasattr(node, "original_router"):
            context = getattr(node, "include_context", None)
            include_prefix = getattr(context, "prefix", "") or ""
            router = node.original_router
            # A router's own prefix is already part of each of its routes' paths.
            yield from _walk(router.routes, prefix + include_prefix)
        elif hasattr(node, "routes") and not hasattr(node, "path"):  # pragma: no cover
            yield from _walk(node.routes, prefix)
