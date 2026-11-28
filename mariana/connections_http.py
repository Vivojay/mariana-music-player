"""Account operations for the single-user loopback web launcher."""
import json
import os

from .account_services import AccountError
from .connections import hub


def handle_accounts_post(handler):
    return _local_post(handler, "/api/accounts", "X-Mariana-Accounts", lambda args: hub().run(args), 5, 160)


def handle_jam_post(handler):
    from .fanrooms import _origin
    from .jams import run

    def execute(args):
        if not args or args[0].casefold() != "login":
            return run(args)
        configured = os.environ.get("MARIANA_MATRIX_ORIGIN", "").strip()
        if not configured:
            raise AccountError("Sign in with jam login in the native terminal, or configure MARIANA_MATRIX_ORIGIN.")
        approved = _origin(configured)
        if len(args) != 2 or _origin(args[1]) != approved:
            raise AccountError("Browser sign-in must use the Matrix homeserver configured for this launcher.")
        return run(["login", approved])

    return _local_post(handler, "/api/jam", "X-Mariana-Jam", execute, 205, 255)


def _local_post(handler, path, header, execute, max_args, max_arg_size):
    if handler.path != path:
        return False
    host = handler.headers.get("Host", "")
    hosts = {f"127.0.0.1:{handler.server.server_port}", f"localhost:{handler.server.server_port}"}
    if (host not in hosts or handler.headers.get("Origin") != f"http://{host}"
            or handler.headers.get(header) != "1"
            or handler.headers.get_content_type() != "application/json"):
        handler.send_error(403)
        return True
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        if not 0 < length <= 2048:
            raise AccountError("Invalid request size.")
        args = json.loads(handler.rfile.read(length))
        if not isinstance(args, list) or len(args) > max_args or not all(isinstance(arg, str) and len(arg) <= max_arg_size for arg in args):
            raise AccountError("Invalid command arguments.")
        result = execute(args)
        status = 200
    except (AccountError, ValueError, OSError) as error:
        result, status = {"error": str(error)}, 400
    body = json.dumps(result).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True
