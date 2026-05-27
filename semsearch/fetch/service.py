"""Fetch and crawl service using httpx + BeautifulSoup."""

import asyncio
import html
import json
import time
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader


def _is_safe_url(url: str) -> bool:
    """Validate URL to prevent SSRF attacks."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or parsed.scheme not in ('http', 'https'):
            return False
        if not parsed.netloc:
            return False
        hostname = parsed.hostname or ''
        # Block localhost and internal IPs
        blocked = {'localhost', '127.0.0.1', '::1', '0.0.0.0', '::'}
        return not (hostname in blocked or hostname.startswith('192.168.') or hostname.startswith('10.'))
    except Exception:
        return False


def _href_to_str(href: Any) -> str:
    return href if isinstance(href, str) else ""


PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}


class FetchService:
    """Service for fetching web pages and converting to markdown/html/text."""

    def __init__(self, fetch_config: Optional[Any] = None) -> None:
        self.fetch_config = fetch_config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch(
        self,
        url: str,
        format: str = "markdown",
        max_chars: Optional[int] = None,
    ) -> Dict[str, Any]:
        start = time.time()
        if not _is_safe_url(url):
            return {
                "url": url,
                "final_url": url,
                "status": "error",
                "title": "",
                "content": "",
                "format": format,
                "latency_ms": 0,
                "error": "URL is not allowed (invalid scheme, internal IP, or blocked hostname)",
            }
        try:
            client = await self._get_client()
            resp = await client.get(url)
            latency = int((time.time() - start) * 1000)
            final_url = str(resp.url)

            if self._is_pdf_response(resp, final_url):
                content, title, pdf_metadata = self._format_pdf_content(resp.content, final_url, format)
                if max_chars and len(content) > max_chars:
                    content = content[:max_chars]

                return {
                    "url": url,
                    "final_url": final_url,
                    "status": "success" if resp.status_code < 400 else "failed",
                    "title": title,
                    "content": content,
                    "format": format,
                    "latency_ms": latency,
                    "metadata": {
                        "status_code": resp.status_code,
                        "content_length": len(content),
                        "source_content_length": len(resp.content),
                        "content_type": resp.headers.get("content-type", ""),
                        "document_type": "pdf",
                        **pdf_metadata,
                    },
                }

            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else ""

            content = self._format_content(soup, resp.text, final_url, title, format)

            if max_chars and len(content) > max_chars:
                content = content[:max_chars]

            return {
                "url": url,
                "final_url": final_url,
                "status": "success" if resp.status_code < 400 else "failed",
                "title": title,
                "content": content,
                "format": format,
                "latency_ms": latency,
                "metadata": {
                    "status_code": resp.status_code,
                    "content_length": len(content),
                    "content_type": resp.headers.get("content-type", ""),
                    "document_type": "html",
                    "links_count": len(soup.find_all("a")),
                },
            }
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return {
                "url": url,
                "final_url": url,
                "status": "error",
                "title": "",
                "content": "",
                "format": format,
                "latency_ms": latency,
                "error": str(e),
            }

    async def crawl(
        self,
        url: str,
        depth: int = 1,
        max_pages: int = 10,
        format: str = "markdown",
    ) -> Dict[str, Any]:
        if not _is_safe_url(url):
            return {
                "seed_url": url,
                "pages": [],
                "errors": [{"url": url, "error": "URL is not allowed (invalid scheme, internal IP, or blocked hostname)"}],
                "summary": {
                    "total_pages": 0,
                    "total_errors": 1,
                    "depth": depth,
                    "latency_ms": 0,
                },
            }
        start = time.time()
        pages: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        visited: set = set()
        queue: List[tuple] = [(url, 0)]
        semaphore = asyncio.Semaphore(3)

        async def crawl_page(current_url: str, current_depth: int) -> None:
            async with semaphore:
                if current_url in visited or current_depth > depth or len(pages) >= max_pages:
                    return
                visited.add(current_url)
                try:
                    client = await self._get_client()
                    resp = await client.get(current_url)
                    resp.raise_for_status()
                    final_url = str(resp.url)

                    if self._is_pdf_response(resp, final_url):
                        content, title, pdf_metadata = self._format_pdf_content(resp.content, final_url, format)
                        pages.append({
                            "url": final_url,
                            "title": title,
                            "content": content[:5000],
                            "depth": current_depth,
                            "metadata": {
                                "document_type": "pdf",
                                **pdf_metadata,
                            },
                        })
                        return

                    soup = BeautifulSoup(resp.text, "html.parser")
                    title = soup.title.get_text(strip=True) if soup.title else ""

                    content = self._format_content(soup, resp.text, final_url, title, format)

                    pages.append({
                        "url": final_url,
                        "title": title,
                        "content": content[:5000],
                        "depth": current_depth,
                    })

                    if current_depth < depth and len(pages) < max_pages:
                        links = self._extract_links(soup, current_url)
                        for link in links:
                            if link not in visited and _is_safe_url(link):
                                queue.append((link, current_depth + 1))
                except Exception as e:
                    errors.append({"url": current_url, "error": str(e)})

        while queue and len(pages) < max_pages:
            current_url, current_depth = queue.pop(0)
            await crawl_page(current_url, current_depth)

        latency = int((time.time() - start) * 1000)

        return {
            "seed_url": url,
            "pages": pages,
            "errors": errors,
            "summary": {
                "total_pages": len(pages),
                "total_errors": len(errors),
                "depth": depth,
                "latency_ms": latency,
            },
        }

    async def batch_fetch(
        self,
        urls: List[str],
        format: str = "markdown",
        max_chars: Optional[int] = None,
        concurrency: int = 5,
    ) -> Dict[str, Any]:
        """Fetch multiple URLs in parallel with SSRF protection."""
        start = time.time()
        if not isinstance(urls, list):
            return {
                "status": "error",
                "results": [],
                "summary": {
                    "total": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "latency_ms": 0,
                    "concurrency": 0,
                },
                "error": "urls must be a list",
            }
        clean_urls = [url.strip() for url in urls if isinstance(url, str) and url.strip() and _is_safe_url(url.strip())]
        clean_urls = clean_urls[:20]
        try:
            concurrency = int(concurrency)
        except (TypeError, ValueError):
            concurrency = 5
        try:
            max_chars = int(max_chars) if max_chars is not None else None
        except (TypeError, ValueError):
            max_chars = None
        concurrency = max(1, min(concurrency, 10))
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_one(index: int, target_url: str) -> Dict[str, Any]:
            async with semaphore:
                result = await self.fetch(target_url, format=format, max_chars=max_chars)
                result["index"] = index
                return result

        results = await asyncio.gather(*(fetch_one(index, target_url) for index, target_url in enumerate(clean_urls)))
        latency = int((time.time() - start) * 1000)
        success_count = sum(1 for result in results if result.get("status") == "success")

        return {
            "status": "success",
            "results": results,
            "summary": {
                "total": len(results),
                "succeeded": success_count,
                "failed": len(results) - success_count,
                "latency_ms": latency,
                "concurrency": concurrency,
            },
        }

    def _html_to_markdown(self, soup: BeautifulSoup, base_url: str) -> str:
        lines = []

        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "br", "hr"]):
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(element.name[1])
                text = element.get_text(strip=True)
                if text:
                    lines.append(f'{"#" * level} {text}\n')
            elif element.name == "p":
                text = element.get_text(strip=True)
                if text:
                    lines.append(f"{text}\n")
            elif element.name == "li":
                text = element.get_text(strip=True)
                if text:
                    lines.append(f"- {text}")
            elif element.name == "pre":
                text = element.get_text()
                if text:
                    lines.append(f"```\n{text}\n```")
            elif element.name == "blockquote":
                text = element.get_text(strip=True)
                if text:
                    lines.append(f"> {text}\n")
            elif element.name == "br":
                lines.append("")
            elif element.name == "hr":
                lines.append("---\n")

        for a in soup.find_all("a", href=True):
            href = _href_to_str(a.get("href"))
            if not href.startswith(("javascript:", "mailto:", "#")):
                full_url = urljoin(base_url, href)
                text = a.get_text(strip=True)
                if text and text != href:
                    lines.append(f"[{text}]({full_url})")

        if not lines:
            return soup.get_text(strip=True)

        return "\n".join(lines)

    def _format_content(
        self,
        soup: BeautifulSoup,
        html: str,
        final_url: str,
        title: str,
        format: str,
    ) -> str:
        if format == "html":
            return html
        if format == "text":
            return soup.get_text(separator="\n", strip=True)
        if format == "json":
            return self._html_to_json(soup, final_url, title)
        if format == "xml":
            return self._html_to_xml(soup, final_url, title)
        return self._html_to_markdown(soup, final_url)

    def _is_pdf_response(self, resp: httpx.Response, final_url: str) -> bool:
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        path = urlparse(final_url).path.lower()
        return content_type in PDF_CONTENT_TYPES or path.endswith(".pdf") or resp.content.startswith(b"%PDF")

    def _format_pdf_content(self, pdf_bytes: bytes, final_url: str, format: str) -> tuple[str, str, Dict[str, Any]]:
        title, pages = self._extract_pdf_pages(pdf_bytes)
        title = title or self._title_from_url(final_url)
        text = "\n\n".join(page for page in pages if page).strip()
        metadata = {
            "page_count": len(pages),
            "links_count": 0,
        }

        if format == "json":
            content = json.dumps(
                {
                    "url": final_url,
                    "title": title,
                    "page_count": len(pages),
                    "pages": [{"page": index + 1, "text": page} for index, page in enumerate(pages)],
                    "text": text,
                },
                ensure_ascii=False,
                indent=2,
            )
        elif format == "xml":
            page_nodes = [
                f'  <page number="{index + 1}">{self._esc_xml(page)}</page>'
                for index, page in enumerate(pages)
                if page
            ]
            content = "\n".join([
                '<?xml version="1.0" encoding="UTF-8"?>',
                "<pdf>",
                f"  <url>{self._esc_xml(final_url)}</url>",
                f"  <title>{self._esc_xml(title)}</title>",
                *page_nodes,
                "</pdf>",
            ])
        elif format == "html":
            escaped_text = html.escape(text)
            escaped_title = html.escape(title)
            content = f"<!doctype html><html><head><title>{escaped_title}</title></head><body><pre>{escaped_text}</pre></body></html>"
        elif format == "text":
            content = text
        else:
            content = f"# {title}\n\n{text}" if title else text

        return content, title, metadata

    def _extract_pdf_pages(self, pdf_bytes: bytes) -> tuple[str, List[str]]:
        reader = PdfReader(BytesIO(pdf_bytes))
        title = ""
        if reader.metadata:
            title = str(getattr(reader.metadata, "title", "") or "").strip()
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return title, pages

    def _title_from_url(self, final_url: str) -> str:
        path = urlparse(final_url).path.rstrip("/")
        if not path:
            return final_url
        name = path.rsplit("/", 1)[-1]
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        return name.replace("-", " ").replace("_", " ").strip() or final_url

    def _html_to_json(self, soup: BeautifulSoup, final_url: str, title: str) -> str:
        data = {
            "url": final_url,
            "title": title,
            "headings": [],
            "paragraphs": [],
            "links": [],
        }
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            text = h.get_text(strip=True)
            if text:
                data["headings"].append({"level": h.name, "text": text})
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                data["paragraphs"].append(text)
        for a in soup.find_all("a", href=True):
            href = _href_to_str(a.get("href"))
            text = a.get_text(strip=True)
            if not href.startswith(("javascript:", "mailto:", "#")):
                data["links"].append({"text": text, "url": urljoin(final_url, href)})
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _html_to_xml(self, soup: BeautifulSoup, final_url: str, title: str) -> str:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines.append("<page>")
        lines.append(f"  <url>{self._esc_xml(final_url)}</url>")
        lines.append(f"  <title>{self._esc_xml(title)}</title>")
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            text = h.get_text(strip=True)
            if text:
                lines.append(f"  <{h.name}>{self._esc_xml(text)}</{h.name}>")
        for p in soup.find_all("p"):
            text = p.get_text(strip=True)
            if text:
                lines.append(f"  <p>{self._esc_xml(text)}</p>")
        for a in soup.find_all("a", href=True):
            href = _href_to_str(a.get("href"))
            text = a.get_text(strip=True)
            if not href.startswith(("javascript:", "mailto:", "#")):
                lines.append(f'  <link url="{self._esc_xml(urljoin(final_url, href))}">{self._esc_xml(text)}</link>')
        lines.append("</page>")
        return "\n".join(lines)

    def _esc_xml(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        links: List[str] = []
        base_domain = urlparse(base_url).netloc

        for a in soup.find_all("a", href=True):
            href = _href_to_str(a.get("href"))
            if href.startswith(("javascript:", "mailto:", "#")):
                continue
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.netloc and parsed.netloc != base_domain:
                continue
            if parsed.scheme in ("http", "https"):
                links.append(full_url)

        return links[:50]
