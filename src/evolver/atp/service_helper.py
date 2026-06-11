"""ATP service helper — publish and update merchant service listings.

Equivalent to ``evolver/src/atp/serviceHelper.js``.
"""

from __future__ import annotations

from typing import Any

from evolver.atp.hub_client import publish_service, update_service
from evolver.atp.protocol import ServiceListing


async def publish(
    title: str,
    description: str,
    capabilities: list[str],
    *,
    use_cases: list[str] | None = None,
    price_per_task: float = 1.0,
    execution_mode: str = "exclusive",
    max_concurrent: int = 3,
    category: str = "skill",
) -> dict[str, Any]:
    """Publish a new service to the Hub."""
    listing = ServiceListing(
        title=title,
        description=description,
        capabilities=capabilities,
        use_cases=use_cases or [],
        price_per_task=max(price_per_task, 1.0),
        execution_mode=execution_mode,  # type: ignore[arg-type]
        max_concurrent=max_concurrent,
        category=category,  # type: ignore[arg-type]
    )
    return await publish_service(listing.model_dump(exclude_none=True))


async def update(
    service_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Update an existing service listing."""
    return await update_service(service_id, kwargs)
