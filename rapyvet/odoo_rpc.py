from __future__ import annotations

import http.client
import xmlrpc.client
from urllib.parse import urlparse


DEFAULT_ODOO_TIMEOUT_SECONDS = 15.0


class TimeoutTransport(xmlrpc.client.Transport):
    """Transporte XML-RPC HTTP con un límite para conexión y lectura."""

    def __init__(self, timeout: float = DEFAULT_ODOO_TIMEOUT_SECONDS) -> None:
        super().__init__()
        self.timeout = float(timeout)

    def make_connection(self, host: str) -> http.client.HTTPConnection:
        if self._connection and host == self._connection[0]:
            return self._connection[1]

        connection_host, self._extra_headers, _ = self.get_host_info(host)
        connection = http.client.HTTPConnection(
            connection_host,
            timeout=self.timeout,
        )
        self._connection = host, connection
        return connection


class TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    """Transporte XML-RPC HTTPS con un límite para conexión y lectura."""

    def __init__(self, timeout: float = DEFAULT_ODOO_TIMEOUT_SECONDS) -> None:
        super().__init__()
        self.timeout = float(timeout)

    def make_connection(self, host: str) -> http.client.HTTPSConnection:
        if self._connection and host == self._connection[0]:
            return self._connection[1]

        connection_host, self._extra_headers, x509 = self.get_host_info(host)
        connection = http.client.HTTPSConnection(
            connection_host,
            timeout=self.timeout,
            context=self.context,
            **(x509 or {}),
        )
        self._connection = host, connection
        return connection


def crear_proxy_odoo(
    base_url: str,
    endpoint: str,
    *,
    timeout: float = DEFAULT_ODOO_TIMEOUT_SECONDS,
) -> xmlrpc.client.ServerProxy:
    """Crea un proxy de Odoo que no puede bloquear la app indefinidamente."""

    url = str(base_url).rstrip("/")
    scheme = urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("La URL de Odoo debe comenzar con http:// o https://.")

    transport: xmlrpc.client.Transport
    if scheme == "https":
        transport = TimeoutSafeTransport(timeout)
    else:
        transport = TimeoutTransport(timeout)

    return xmlrpc.client.ServerProxy(
        f"{url}/{endpoint.lstrip('/')}",
        allow_none=True,
        transport=transport,
    )

