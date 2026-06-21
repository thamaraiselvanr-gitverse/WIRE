import structlog
from playwright.async_api import Page, Route

logger = structlog.get_logger(__name__)


class NetworkMonitor:
    """
    Request interception, API endpoint discovery, and dynamic data detection.
    Monitors all network traffic during page load to identify API patterns.
    """

    def __init__(self):
        self.captured_requests: list[dict] = []
        self.api_endpoints: list[dict] = []
        self.dynamic_data: list[dict] = []

    async def start_monitoring(self, page: Page) -> None:
        logger.info("starting_network_monitoring")

        page.on("request", self._on_request)
        page.on("response", self._on_response)

    def _on_request(self, request) -> None:
        self.captured_requests.append({
            "url": request.url,
            "method": request.method,
            "resource_type": request.resource_type,
            "headers": dict(request.headers) if request.headers else {},
        })

    def _on_response(self, response) -> None:
        url = response.url
        content_type = response.headers.get("content-type", "")

        # Detect API endpoints (JSON responses)
        if "application/json" in content_type or "/api/" in url:
            self.api_endpoints.append({
                "url": url,
                "status": response.status,
                "content_type": content_type,
                "method": response.request.method,
            })

        # Detect dynamic data sources (XHR/fetch)
        if response.request.resource_type in ("xhr", "fetch"):
            self.dynamic_data.append({
                "url": url,
                "type": response.request.resource_type,
                "status": response.status,
                "content_type": content_type,
            })

    def get_report(self) -> dict:
        report = {
            "total_requests": len(self.captured_requests),
            "api_endpoints": self.api_endpoints,
            "dynamic_data_sources": self.dynamic_data,
            "resource_breakdown": {},
        }

        # Build resource breakdown
        for req in self.captured_requests:
            r_type = req["resource_type"]
            report["resource_breakdown"][r_type] = report["resource_breakdown"].get(r_type, 0) + 1

        logger.info(
            "network_monitoring_report",
            total=report["total_requests"],
            apis=len(report["api_endpoints"]),
            dynamic=len(report["dynamic_data_sources"]),
        )
        return report

    def reset(self) -> None:
        self.captured_requests.clear()
        self.api_endpoints.clear()
        self.dynamic_data.clear()
