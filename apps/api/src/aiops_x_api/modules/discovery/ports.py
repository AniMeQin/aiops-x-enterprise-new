from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DiscoveryObservation:
    ip_address: str
    open_ports: tuple[int, ...]


class DiscoveryBackend(Protocol):
    async def discover(
        self,
        *,
        networks: tuple[str, ...],
        ports: tuple[int, ...],
        timeout_seconds: float,
        max_hosts: int,
    ) -> list[DiscoveryObservation]: ...
