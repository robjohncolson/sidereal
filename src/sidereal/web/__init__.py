"""Optional localhost web application for the Sidereal personal desk."""

from .app import HostGuardMiddleware, WebSettings, create_app

__all__ = ["HostGuardMiddleware", "WebSettings", "create_app"]
