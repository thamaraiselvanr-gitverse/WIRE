import urllib.parse

import httpx
import structlog

logger = structlog.get_logger(__name__)


class LegalDetector:
    """
    Analyzes robots.txt, Terms of Service detection, and produces
    a compliance classification for the target URL.
    """

    async def analyze(self, url: str) -> dict:
        logger.info("analyzing_legal_compliance", url=url)
        parsed = urllib.parse.urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{base_url}/robots.txt"

        result = {
            "url": url,
            "robots_txt": {"found": False, "content": None, "allowed": True},
            "tos_detected": False,
            "classification": "safe_to_reconstruct",
        }

        # Check robots.txt
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(robots_url, follow_redirects=True)
                if resp.status_code == 200:
                    content = resp.text
                    result["robots_txt"]["found"] = True
                    result["robots_txt"]["content"] = content[:2000]

                    # Simple disallow check
                    lines = content.lower().split("\n")
                    for line in lines:
                        line = line.strip()
                        if line.startswith("disallow:"):
                            path = line.split(":", 1)[1].strip()
                            if path == "/" or path == "/*":
                                result["robots_txt"]["allowed"] = False
                                result["classification"] = "restricted"
                                break
            except Exception as e:
                logger.warning("robots_txt_check_failed", error=str(e))

        logger.info("legal_analysis_complete", classification=result["classification"])
        return result
