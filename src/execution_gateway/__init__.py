"""Optional, process-separated execution for independently configured agents."""

from .client import Client, GatewayError

__all__ = ["Client", "GatewayError"]
