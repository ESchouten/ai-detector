"""Local TLS certificates for download and executable tests; never installed globally."""

import ssl
from http.server import ThreadingHTTPServer
from pathlib import Path

import trustme


def enable_https(server: ThreadingHTTPServer, ca_file: Path) -> None:
    authority = trustme.CA()
    authority.cert_pem.write_to_path(ca_file)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    authority.issue_cert("127.0.0.1").configure_cert(context)
    server.socket = context.wrap_socket(server.socket, server_side=True)
