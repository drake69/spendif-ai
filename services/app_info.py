"""Application build metadata, exposed to the UI via the service layer.

Keeps the UI decoupled from `core.*`: the `core._build_info` module is generated
at build time, so the `from core` import lives here (service layer, allowed) and
the UI consumes `get_build_info()` instead.
"""


def get_build_info() -> tuple[str, str]:
    """Return (version, build_time).

    Falls back to ("dev", "dev") when running from source (no frozen build stamp).
    """
    try:
        from core._build_info import BUILD_TIME, BUILD_VERSION
    except ImportError:
        return "dev", "dev"
    return BUILD_VERSION, BUILD_TIME
