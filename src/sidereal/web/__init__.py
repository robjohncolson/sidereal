"""Optional localhost web application for the Sidereal personal desk."""

from .app import HostGuardMiddleware, ScopedCORSMiddleware, WebSettings, create_app

__all__ = ["HostGuardMiddleware", "ScopedCORSMiddleware", "WebSettings", "create_app"]
