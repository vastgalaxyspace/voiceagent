"""Container readiness probe; loopback only, without credentials or logs."""
import sys
from urllib.request import ProxyHandler, build_opener


def main():
    try:
        # Ignore inherited HTTP_PROXY settings for a local-only health probe.
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:8000/health/ready', timeout=6) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == '__main__':
    sys.exit(main())
