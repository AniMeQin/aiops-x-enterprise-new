import asyncio
import ipaddress

from aiops_x_api.core.errors import ApplicationError
from aiops_x_api.modules.discovery.ports import DiscoveryObservation

_RFC1918: tuple[ipaddress.IPv4Network, ...] = tuple(
    ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


class AsyncTcpDiscoveryBackend:
    """Bounded, read-only TCP connect discovery for explicitly configured RFC1918 ranges."""

    async def discover(
        self,
        *,
        networks: tuple[str, ...],
        ports: tuple[int, ...],
        timeout_seconds: float,
        max_hosts: int,
    ) -> list[DiscoveryObservation]:
        hosts = self._hosts(networks, max_hosts)
        semaphore = asyncio.Semaphore(64)

        async def observe(address: str) -> DiscoveryObservation | None:
            open_ports: list[int] = []
            for port in ports:
                if await self._port_open(address, port, timeout_seconds, semaphore):
                    open_ports.append(port)
            if not open_ports:
                return None
            return DiscoveryObservation(ip_address=address, open_ports=tuple(open_ports))

        rows = await asyncio.gather(*(observe(address) for address in hosts))
        return [row for row in rows if row is not None]

    @staticmethod
    def _hosts(networks: tuple[str, ...], max_hosts: int) -> list[str]:
        result: list[str] = []
        for value in networks:
            network = ipaddress.ip_network(value, strict=False)
            if network.version != 4 or not any(network.subnet_of(parent) for parent in _RFC1918):
                raise ApplicationError(
                    code="AIOPS_3301",
                    message="发现任务只允许明确配置的 RFC1918 私网 IPv4 网段",
                    status_code=422,
                )
            for host in network.hosts():
                result.append(str(host))
                if len(result) > max_hosts:
                    raise ApplicationError(
                        code="AIOPS_3302",
                        message="发现任务主机数超过安全上限",
                        status_code=422,
                    )
        if not result:
            raise ApplicationError(
                code="AIOPS_3303", message="发现网段不包含可探测主机", status_code=422
            )
        return result

    @staticmethod
    async def _port_open(
        address: str, port: int, timeout_seconds: float, semaphore: asyncio.Semaphore
    ) -> bool:
        async with semaphore:
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(address, port), timeout=timeout_seconds
                )
            except (TimeoutError, OSError):
                return False
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return True
