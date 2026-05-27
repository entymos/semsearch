# SemSearch Technical Wiki

A comprehensive technical guide to SemSearch's MCP Tools, explaining how they work internally, search engine implementations, and data retrieval mechanisms.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [MCP Tools](#mcp-tools)
   - [Web Search Tool](#web-search-tool)
   - [Web Fetch Tool](#web-fetch-tool)
   - [Batch Fetch Tool](#batch-fetch-tool)
   - [Crawl Tool](#crawl-tool)
   - [Search with Fetch (sem_search) Tool](#search-with-fetch-sem_search-tool)
3. [Result Ranking Algorithm](#result-ranking-algorithm)
4. [Search Engines Guide](#search-engines-guide)
   - [Built-In Engines Overview](#built-in-engines-overview)
   - [Engine Selection & Diagnostics](#engine-selection--diagnostics)
   - [Practical Engine Combinations](#practical-engine-combinations)
   - [Detailed Engine Analysis](#detailed-engine-analysis)
5. [HTML Processing & Format Conversion](#html-processing--format-conversion)
6. [Metadata & Performance](#metadata--performance)
7. [Error Handling](#error-handling)
8. [Security Considerations](#security-considerations)
9. [Comparison with SearXNG](#comparison-with-searxng)
10. [Conclusion](#conclusion)

---

## Architecture Overview

### Complete Flow Diagram

```
User Input
    ↓
MCP Tool Call
    ├── web_search: Search only
    ├── web_fetch: Fetch single URL
    ├── batch_fetch: Parallel multi-URL processing
    ├── crawl: Website crawling
    └── sem_search: Search + Auto-fetch
    ↓
Search Engine Adapters (SearchService)
    ├── Google, Bing, DuckDuckGo, ...
    └── Per-engine HTML parsing or API calls
    ↓
Fetch Service (FetchService)
    ├── HTTP requests (httpx)
    ├── HTML parsing (BeautifulSoup)
    └── Format conversion (Markdown/JSON/XML/Text)
    ↓
Return Results
```

### Core Components

1. **SearchService**: Multi-engine search orchestration
2. **EngineAdapter**: Base adapter class for each search engine
3. **FetchService**: Web page fetching and format conversion
4. **EngineRegistry**: Manages registered search engines

---

## MCP Tools

### Web Search Tool

#### Input Parameters

```python
{
    "q": "search query",           # Required: Search keyword
    "engines": "google,bing",      # Optional: Specific engines only
    "limit": 10,                   # Optional: Results (default 10, max 50)
    "language": "en",              # Optional: Language code (en, ko, etc)
    "time_range": "week",          # Optional: Time range (day/week/month/year)
    "include_domains": ["github.com"],  # Optional: Only these domains
    "exclude_domains": ["facebook.com"] # Optional: Exclude these domains
}
```

#### Internal Processing

```
User keyword input
    ↓
[1] Engine Selection
    - If engines param exists, use only those
    - Otherwise, use all enabled engines from config
    - Non-existent engines return warning
    ↓
[2] Parallel search per engine (asyncio.gather)
    - Call each adapter's search() method
    - Timeout: engine default or config value
    - Failed engines return error info
    ↓
[3] Result post-processing
    a) Deduplication (by URL)
    b) Domain filtering
       - include_domains: only specified domains
       - exclude_domains: remove specified domains
    c) Query-based ranking (simple word matching)
    d) Return top limit results
    ↓
Return Results
{
    "results": [
        {
            "title": "...",
            "url": "...",
            "snippet": "...",
            "engine": "google",
            "score": 0.95,
            "published_date": "2024-01-01T00:00:00Z",
            "metadata": {}
        }
    ],
    "query": "search query",
    "total_results": 5,
    "engine_errors": [...],
    "warnings": [...]
}
```

### Web Fetch Tool

#### Input Parameters

```python
{
    "url": "https://example.com",  # Required: URL to fetch
    "format": "markdown",          # Optional: markdown/html/text/json/xml (default: markdown)
    "max_chars": 50000            # Optional: Maximum characters
}
```

#### Internal Processing

```
URL input
    ↓
[1] URL Validation (SSRF Prevention)
    - Scheme check: only http, https
    - Block internal IPs: 127.0.0.1, 192.168.*, 10.* etc
    - Block localhost: localhost, ::1, 0.0.0.0 etc
    ↓
[2] HTTP Request
    - User-Agent: Chrome simulation
    - Auto-follow redirects
    - Timeout: 30 seconds
    - Track final URL
    ↓
[3] Content-type handling
    a) PDF detection
       - Check Content-Type header
       - Check URL path (.pdf extension)
       - Check file signature (%PDF)
       ↓
       PDF Processing:
       - Extract text using PyPDF
       - Extract per-page text
       - Extract metadata (title, page count)
       - Convert per format
    
    b) HTML files
       ↓
       HTML Processing:
       - Parse with BeautifulSoup
       - Extract title tag
       - Convert content per format
    ↓
[4] HTML Content Format Conversion
    Based on format parameter:
    
    a) Markdown format:
       - <h1~6> → # Title (by level)
       - <p> → Plain text
       - <li> → - List item
       - <pre> → ``` code block ```
       - <blockquote> → > Quote
       - <a href="...">text</a> → [text](url)
       - Auto HTML entity decoding
       - Normalize line breaks
    
    b) Plain Text format:
       - Remove all HTML tags
       - Extract text only
       - Separated by line breaks
    
    c) JSON format:
       {
           "url": "...",
           "title": "...",
           "headings": [{"level": "h2", "text": "..."}],
           "paragraphs": ["..."],
           "links": [{"text": "...", "url": "..."}]
       }
    
    d) XML format:
       <?xml version="1.0" encoding="UTF-8"?>
       <page>
           <url>...</url>
           <title>...</title>
           <heading level="2">...</heading>
           <paragraph>...</paragraph>
           <link href="...">...</link>
       </page>
    
    e) HTML format:
       - Return original HTML as-is
    ↓
[5] Apply size limits
    - Truncate content by max_chars if set
    ↓
Return Results
{
    "url": "https://example.com",
    "final_url": "https://example.com/redirected",
    "status": "success",
    "title": "Page Title",
    "content": "# Page Title\n\nContent...",
    "format": "markdown",
    "latency_ms": 1250,
    "metadata": {
        "status_code": 200,
        "content_length": 5000,
        "content_type": "text/html; charset=utf-8",
        "document_type": "html",
        "links_count": 42
    }
}
```

### Batch Fetch Tool

#### Input Parameters

```python
{
    "urls": ["https://example1.com", "https://example2.com"],  # Required: URL list (max 20)
    "format": "markdown",                                        # Optional: format
    "max_chars": 50000,                                          # Optional: max characters
    "concurrency": 5                                             # Optional: parallel workers (1-10)
}
```

#### Internal Processing

```
URL list input
    ↓
[1] URL Validation & Cleanup
    - Validate each URL (SSRF prevention)
    - Process max 20 URLs
    - No deduplication
    ↓
[2] Parallel Processing Setup
    - Set concurrent connections (Semaphore)
    - Default 5, min 1, max 10
    ↓
[3] Parallel fetch each URL
    - Use asyncio.gather() for concurrent processing
    - Each URL same process as web_fetch
    - Failed URLs included in results
    ↓
[4] Collect Results
    - Track original order with indices
    - Calculate success/failure stats
    ↓
Return Results
{
    "status": "success",
    "results": [
        {
            "index": 0,
            "url": "https://example1.com",
            "status": "success",
            "title": "...",
            "content": "...",
            "latency_ms": 1250
        },
        {
            "index": 1,
            "url": "https://example2.com",
            "status": "error",
            "error": "Connection timeout"
        }
    ],
    "summary": {
        "total": 2,
        "succeeded": 1,
        "failed": 1,
        "latency_ms": 2500,
        "concurrency": 5
    }
}
```

#### Parallel Processing Benefits

- **Speed**: 5 URLs processed concurrently ~5x faster than sequential
- **Efficiency**: Other work continues during IO wait
- **Controlled**: Concurrency limits prevent server overload

### Crawl Tool

#### Input Parameters

```python
{
    "url": "https://example.com",  # Required: Starting URL
    "depth": 1,                    # Optional: Crawl depth (1-5, default 1)
    "max_pages": 10,               # Optional: Max pages (1-100, default 10)
    "format": "markdown"           # Optional: Content format
}
```

#### Internal Processing

```
Starting URL input
    ↓
[1] URL & Depth Validation
    - Validate starting URL (SSRF prevention)
    - Check depth range (1-5)
    ↓
[2] Initialize crawl queue
    - Add (url, depth=0) to queue
    - Initialize visited set
    ↓
[3] Crawl loop
    while queue not empty and pages < max_pages:
        
        a) Extract URL from queue
        b) Check if already visited
           - If visited, skip
           - If not, proceed
        
        c) Fetch URL (parallel, concurrency: 3)
           - Detect and process PDFs
           - Parse HTML
        
        d) Store content
           - URL, title, content (5000 char limit), depth
        
        e) Extract next depth URLs (if depth < max_depth)
           - Extract all <a href="..."> from current page
           - Convert relative URLs to absolute
           - Validate safety, add to queue
    ↓
[4] Collect Results
    - List of successful pages
    - List of errors
    ↓
Return Results
{
    "seed_url": "https://example.com",
    "pages": [
        {
            "url": "https://example.com",
            "title": "Home",
            "content": "...",
            "depth": 0,
            "metadata": {"document_type": "html"}
        },
        {
            "url": "https://example.com/about",
            "title": "About",
            "content": "...",
            "depth": 1
        }
    ],
    "errors": [
        {
            "url": "https://example.com/broken",
            "error": "HTTP 404 Not Found"
        }
    ],
    "summary": {
        "total_pages": 2,
        "total_errors": 1,
        "depth": 1,
        "latency_ms": 5000
    }
}
```

#### Crawling Strategy

- **Breadth-First Search (BFS)**: Process by depth level
- **Duplicate Prevention**: Don't revisit URLs
- **Parallel Processing**: Max 3 concurrent page fetches
- **Resource Limits**: Max pages prevents infinite loops

### Search with Fetch (sem_search) Tool

#### Input Parameters

```python
{
    "q": "search query",              # Required: Search keyword
    "engines": "google,bing",         # Optional: Specific engines
    "limit": 10,                      # Optional: Result count
    "fetch_top": 3,                   # Optional: Auto-fetch top N results
    "include_domains": ["github.com"],# Optional: Only these domains
    "exclude_domains": ["facebook.com"]# Optional: Exclude these domains
}
```

#### Internal Processing

```
User search keyword input
    ↓
[1] Execute Web Search
    - Same process as web_search
    - Obtain search results
    ↓
[2] Auto-fetch top results (fetch_top parameter)
    if fetch_top > 0:
        a) Extract top N URLs
        b) Parallel fetch via batch_fetch
           - Concurrency: 5
           - Format: markdown
        
        c) Add fetched content to each result
           {
               "title": "...",
               "url": "...",
               "snippet": "...",
               "engine": "google",
               "content": "# Page Title\n\nFull page content..." // Added
           }
    ↓
[3] Return Results
{
    "results": [
        {
            "title": "...",
            "url": "...",
            "snippet": "...",
            "engine": "google",
            "content": "...",  // Only if fetch_top > 0
            "fetch_status": "success",
            "fetch_latency_ms": 1250
        }
    ],
    "query": "search query",
    "fetch_top": 3,
    "summary": {
        "total_results": 10,
        "fetched_results": 3,
        "fetch_succeeded": 3,
        "fetch_failed": 0
    }
}
```

#### Use Cases

- **Information Gathering**: Search + auto-fetch top 3 pages
- **Summarization**: Auto-collect then summarize results
- **Decision Making**: Get full content from multiple sources at once

---

## Result Ranking Algorithm

### Score Calculation Process

SemSearch uses **simple word matching-based** scoring:

```python
def _rank(self, results: List[SearchResult], query: str) -> List[SearchResult]:
    query_terms = set(query.lower().split())
    for r in results:
        score = r.score  # Existing engine score (e.g., GitHub stars, HN points)
        
        # Match query terms in title (weight: 2.0)
        title_matches = sum(1 for t in query_terms if t in r.title.lower())
        score += title_matches * 2.0
        
        # Match query terms in snippet (weight: 0.5)
        snippet_matches = sum(1 for t in query_terms if t in r.snippet.lower())
        score += snippet_matches * 0.5
        
        r.score = round(score, 3)
    
    # Sort by final score descending
    return sorted(results, key=lambda x: x.score, reverse=True)
```

### Example

**Search term**: "python machine learning"  
**Query terms**: {"python", "machine", "learning"}

**Result calculation**:

```json
{
    "title": "Python Machine Learning Tutorial",
    "snippet": "Learn Python and machine learning basics",
    "engine": "google",
    "score": 0.0
}

// Calculation:
// 1. Initial score: 0.0
// 2. Title matches: "python" + "machine" + "learning" = 3 → 3 * 2.0 = 6.0
// 3. Snippet matches: "python" + "machine" + "learning" = 3 → 3 * 0.5 = 1.5
// 4. Final score: 0.0 + 6.0 + 1.5 = 7.5
```

### Characteristics

- **Simple & Fast**: O(n*m) complexity (n: results, m: query terms)
- **Transparent**: Intuitive score calculation
- **Engine Score Utilization**: GitHub stars, HN points included as base score
- **Substring Matching**: "learning" matches "machine-learning"

### Comparison with BM25

| Item | Current | BM25 |
|------|---------|------|
| **Algorithm** | Simple word matching | TF-IDF based |
| **Document length normalization** | ❌ No | ✅ Yes |
| **IDF Calculation** | ❌ No | ✅ Corpus-based |
| **Parameters** | Fixed (2.0, 0.5) | Tunable (k1, b) |
| **Implementation complexity** | Low | High |
| **Use case** | Multi-engine result merging | Single corpus search |
| **Response time** | Very fast | Medium |

### When is it used?

1. **Multi-engine result merging**: Combining results from Google, Bing, DuckDuckGo etc
2. **After domain filtering**: Re-rank after filtering to specific domains
3. **When fast response needed**: Minimize API latency

### Future Improvements

- Upgrade to BM25 implementation
- Add corpus-based IDF calculation
- Add per-engine trust weights
- Add user feedback-based learning (Learning to Rank)

---

## Search Engines Guide

### Built-In Engines Overview

SemSearch ships with free, no-key engines covering different research needs. General web engines provide breadth, while API-backed reference engines give stable structured results.

| Engine | Category | Default | Source | Best for |
| --- | --- | --- | --- | --- |
| DuckDuckGo | general | enabled | HTML | General web search with privacy-friendly defaults |
| Qwant | general | enabled | JSON API | European/privacy search coverage |
| Startpage | general | enabled | HTML | Privacy meta-search coverage |
| Wikipedia | reference | enabled | JSON API | Encyclopedia and reference lookups |
| arXiv | academic | enabled | Atom API | Academic papers and preprints |
| Hacker News | community | enabled | Algolia HN API | Developer discussions and launch context |
| GitHub Repositories | code | enabled | GitHub REST API | Open-source repository discovery |
| Bing | general | disabled | HTML | Additional general web coverage |
| Google | general | disabled | HTML | Local testing only; ToS/rate-limit risk |

### Engine Selection & Diagnostics

#### Engine Probes

Dashboard engine probes run live searches. Each probe records:

- status: `ok`, `degraded`, `timeout`, or `error`
- latency in milliseconds
- result count
- probe query
- up to three sample result titles and URLs
- cumulative success/failure counters

REST API example:

```http
POST /api/engines/github/probe?query=weather
Authorization: Bearer <token>
```

MCP example:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "web_search",
    "arguments": {
      "q": "python async web framework",
      "engines": "duckduckgo,github,hackernews",
      "limit": 5
    }
  }
}
```

#### Engine Selection Examples

REST:
```http
GET /api/search?q=python&engines=duckduckgo,wikipedia,github&limit=10
```

MCP:
```json
{
  "q": "python async web framework",
  "engines": "duckduckgo,github,hackernews"
}
```

### Practical Engine Combinations

- **General research**: `duckduckgo,qwant,startpage`
- **Technical due diligence**: `duckduckgo,github,hackernews`
- **Academic research**: `arxiv,wikipedia,duckduckgo`
- **Code/project discovery**: `github,hackernews,duckduckgo`

### Detailed Engine Analysis

#### 1. DuckDuckGo (Privacy-Focused)

**Characteristics:**
- No user tracking (privacy focus)
- HTML interface (not data-based)
- Fast response
- Lenient rate limiting

**How it works:**

```
Search query
    ↓
POST https://html.duckduckgo.com/html/
    Parameters: q=query, kl=language, df=time_range
    ↓
HTML response
    ↓
Parse with BeautifulSoup
    - CSS selector: div.results_links
    - Title: a.result__a
    - Snippet: a.result__snippet
    - URL: href attribute (uddg parameter decoding)
    ↓
Return SearchResult list
```

**Special notes:**
- URLs encoded as redirects (uddg parameter)
- Extract actual URL from query string
- Language code format: ko (simple)

**Time range mapping:**
- day → d
- week → w
- month → m
- year → y

#### 2. Qwant (European Privacy)

**Characteristics:**
- GDPR compliant
- Provides JSON API
- Privacy-focused
- Europe-based

**How it works:**

```
Search query
    ↓
GET https://api.qwant.com/v3/search/web
    Parameters: q=query, locale=language, count=limit
    ↓
JSON response
{
    "data": {
        "result": {
            "items": [
                {
                    "title": "...",
                    "url": "...",
                    "description": "..."
                }
            ]
        }
    }
}
    ↓
Parse JSON and convert to SearchResult
    ↓
Return results
```

**Special notes:**
- API-based, very stable
- No HTML parsing needed
- Deep JSON structure (data.result.items)

**Language code format:**
- en, fr, de, ko etc (ISO 639-1)

#### 3. Startpage (Privacy Meta-Search)

**Characteristics:**
- Private Google results
- HTML-based scraping
- Stable and accurate results

**How it works:**
- Similar HTML parsing to DuckDuckGo
- CSS selectors for result extraction
- Google-level search quality

#### 4. Wikipedia (Reference)

**Characteristics:**
- Official API (fully stable)
- Optimal for technical docs, encyclopedic info
- Returns HTML snippets (with tags)

**How it works:**

```
Search query
    ↓
GET https://{lang}.wikipedia.org/w/api.php
    Parameters:
    - action=query
    - list=search
    - srsearch=query
    - srlimit=limit
    - srprop=snippet|timestamp|wordcount
    ↓
JSON response
{
    "query": {
        "search": [
            {
                "title": "Page Title",
                "snippet": "<span class='...'>HTML snippets</span>",
                "timestamp": "2024-01-01T00:00:00Z"
            }
        ]
    }
}
    ↓
Clean HTML snippets
    - Parse with BeautifulSoup
    - Extract text only (remove HTML tags)
    ↓
Generate URLs
    - https://{lang}.wikipedia.org/wiki/{title}
    - Convert spaces to underscores
    ↓
Return SearchResult
```

**Special notes:**
- Official API, very stable
- HTML markup in snippets
- timestamp becomes published_date
- Auto language support (ko, en, ja etc)

#### 5. arXiv (Academic Papers)

**Characteristics:**
- Specialized for academic papers
- Atom XML API
- Authors, publication date, abstracts included
- Optimal for academic search

**How it works:**

```
Search query
    ↓
GET https://export.arxiv.org/api/query
    Parameters:
    - search_query=all:{query} (all fields)
    - max_results=limit
    - sortBy=relevance
    - sortOrder=descending
    ↓
Atom XML response
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <entry>
        <title>Paper Title</title>
        <id>http://arxiv.org/abs/1234.5678</id>
        <summary>Abstract text...</summary>
        <published>2024-01-01T00:00:00Z</published>
        <author>
            <name>Author Name</name>
        </author>
    </entry>
</feed>
    ↓
Parse XML (ElementTree)
    - Namespace: xmlns="http://www.w3.org/2005/Atom"
    - Extract with XPath
    ↓
Collect metadata
    - Author list (authors)
    - Publication date (published_date)
    - Paper ID (URL)
    ↓
Return SearchResult
```

**Special notes:**
- XML format, no HTML parsing needed
- Author info in metadata.authors
- Summary is abstract, can be lengthy
- URL is arXiv ID (not actual PDF link)

**Example result:**
```json
{
    "title": "Attention Is All You Need",
    "url": "http://arxiv.org/abs/1706.03762",
    "snippet": "The dominant sequence transduction...",
    "engine": "arxiv",
    "published_date": "2017-06-12T17:58:57Z",
    "metadata": {
        "authors": ["Ashish Vaswani", "Noam Shazeer", ...]
    }
}
```

#### 6. Hacker News (Tech Community)

**Characteristics:**
- Tech news and discussions
- Algolia HN API (public)
- Includes points (popularity) and comment count
- Developer-focused

**How it works:**

```
Search query
    ↓
GET https://hn.algolia.com/api/v1/search
    Parameters:
    - query=search query
    - tags=story (stories only)
    - hitsPerPage=limit
    ↓
JSON response
{
    "hits": [
        {
            "title": "Story Title",
            "story_title": "Alternative Title",
            "url": "https://example.com",
            "author": "username",
            "points": 1000,
            "num_comments": 250,
            "objectID": "12345678",
            "created_at": "2024-01-01T00:00:00Z"
        }
    ]
}
    ↓
Process results
    - title: use title or story_title
    - URL: HN thread link if url missing
    - snippet: "{points} points, {num_comments} comments by {author}"
    - score: points (popularity-based ranking)
    ↓
Return SearchResult
```

**Special notes:**
- Community vote-based ranking (points)
- Comment count shows engagement
- Original article URL may be missing (discussion threads only)
- Time filtering not supported (Algolia API limitation)

**Included metadata:**
```json
{
    "title": "Show HN: Amazing Tool",
    "url": "https://news.ycombinator.com/item?id=12345678",
    "snippet": "1000 points, 250 comments by username",
    "engine": "hackernews",
    "score": 1000,
    "metadata": {
        "points": 1000,
        "comments": 250,
        "author": "username"
    }
}
```

#### 7. GitHub (Source Code)

**Characteristics:**
- Official GitHub REST API
- Repository-focused search
- Stars, forks, issues metadata
- Programming language filtering

**How it works:**

```
Search query + language
    ↓
Add language filter
    - language:{language_code} (e.g., language:python)
    ↓
GET https://api.github.com/search/repositories
    Parameters:
    - q=query + language filter
    - sort=stars (by star count)
    - order=desc
    - per_page=limit
    
    Headers:
    - Accept: application/vnd.github+json
    - X-GitHub-Api-Version: 2022-11-28
    ↓
JSON response
{
    "items": [
        {
            "full_name": "user/repo",
            "html_url": "https://github.com/user/repo",
            "description": "Repository description",
            "stargazers_count": 5000,
            "forks_count": 500,
            "language": "Python",
            "open_issues_count": 42,
            "pushed_at": "2024-01-01T00:00:00Z"
        }
    ]
}
    ↓
Process results
    - title: full_name (user/repo)
    - URL: html_url
    - snippet: "{description} ({stars} stars, {language})"
    - score: stargazers_count (popularity)
    - metadata: detailed info
    ↓
Return SearchResult
```

**Special notes:**
- Official API, very stable
- Language query filter support (language:python)
- Time filtering: pushed:>={date} format
- API rate limit: 30/hour (needs auth)

**Included metadata:**
```json
{
    "title": "openai/gpt-4",
    "url": "https://github.com/openai/gpt-4",
    "snippet": "GPT-4 implementation (50000 stars, Python)",
    "engine": "github",
    "score": 50000,
    "metadata": {
        "stars": 50000,
        "forks": 5000,
        "language": "Python",
        "open_issues": 42
    }
}
```

#### 8. Bing (Microsoft Search)

**Characteristics:**
- Microsoft search engine
- HTML-based scraping
- Image results also available
- More lenient rate limiting than Google

**How it works:**

```
Search query
    ↓
GET https://www.bing.com/search
    Parameters:
    - q=query
    - count=limit
    - setlang={language_code} (ko, en, etc)
    - filters=ex1:ez{time_value} (time range)
    ↓
HTML response
    ↓
Parse with BeautifulSoup
    - CSS selector: li.b_algo
    - Title: h2 a
    - Snippet: p
    ↓
Return SearchResult
```

**Time range mapping:**
- day → 1
- week → 2
- month → 3
- year → 4

**Special notes:**
- Simpler HTML structure than DuckDuckGo
- Clear CSS selectors (b_algo class)
- Result quality similar to Google

#### 9. Google (Google Search)

**Characteristics:**
- Highest search quality
- HTML scraping (official API is paid)
- ⚠️ Strong rate limiting, CAPTCHA, IP blocking possible

**How it works:**

```
Search query
    ↓
GET https://www.google.com/search
    Parameters:
    - q=query
    - num=limit (result count)
    - hl={language_code} (interface language)
    - tbs=qdr:{time_value} (time range)
    
    Headers:
    - User-Agent: Chrome browser simulation
    - Referer: https://www.google.com/
    ↓
HTML response
    ↓
Parse with BeautifulSoup
    - CSS selector: div.g (result items)
    - Title: h3
    - URL: a href
    - Snippet: span.aCOpf
    
    URL redirect handling:
    - Parse /url?q={actual_url}&... format
    - Extract actual URL
    ↓
Return SearchResult
```

**Time range mapping:**
- day → qdr:d
- week → qdr:w
- month → qdr:m
- year → qdr:y

**⚠️ Important Notes:**

1. **IP Blocking**: High request volume can block your IP
2. **CAPTCHA**: May appear if detected as bot
3. **Rate Limiting**: Very strict
4. **ToS Violation**: Scraping may violate Google terms
5. **Recommendation**: Use Google Custom Search Engine or official API in production

**Google API Alternatives:**
- Google Custom Search Engine (paid)
- Programmable Search Engine (low cost)
- Third-party services like Serpapi, SerpWow

---

## HTML Processing & Format Conversion

### Complete Conversion Pipeline

```
Raw HTML
    ↓
BeautifulSoup Parse
    (uses html.parser)
    ↓
Format Selection
    ├── Markdown
    ├── Plain Text
    ├── JSON
    ├── XML
    └── HTML (original)
    ↓
Format-specific Conversion
    ↓
Final Result
```

### 1. Markdown Conversion

**Goal**: Machine-readable and human-friendly format

```python
# Input HTML
<html>
  <body>
    <h1>Main Title</h1>
    <p>Introduction paragraph.</p>
    <h2>Section 1</h2>
    <p>Content for section 1.</p>
    <ul>
      <li>Item 1</li>
      <li>Item 2</li>
    </ul>
    <pre><code>print("Hello")</code></pre>
    <blockquote>Important quote</blockquote>
    <p>Check out <a href="https://example.com">this link</a></p>
  </body>
</html>

# Conversion Process

1. Headings (h1-h6)
   <h1>Title</h1> → "# Title\n"

2. Paragraphs (p)
   <p>Text</p> → "Text\n"

3. Lists (li)
   <li>Item</li> → "- Item"

4. Code blocks (pre)
   <pre><code>code</code></pre> → "```\ncode\n```"

5. Blockquotes (blockquote)
   <blockquote>Quote</blockquote> → "> Quote\n"

6. Links (a)
   <a href="url">text</a> → "[text](url)"

7. Relative URL handling
   - Convert to absolute URLs with urljoin(base_url, href)
   - Exclude javascript: links
   - Exclude mailto: links
   - Exclude # anchors

# Final Markdown Output
# Main Title

Introduction paragraph.

## Section 1

Content for section 1.

- Item 1
- Item 2

```
print("Hello")
```

> Important quote

[this link](https://example.com)
```

**Special notes:**
- Preserves structure (hierarchy)
- Links preserved
- Code blocks clear
- Machine-parseable

### 2. Plain Text Conversion

**Goal**: Extract pure text only

```python
# Use BeautifulSoup's get_text() method
soup.get_text(separator="\n", strip=True)

# How it works:
- Remove all HTML tags
- separator="\n": newlines between block elements
- strip=True: remove leading/trailing whitespace
- Comments, script tags removed

# Output
Main Title
Introduction paragraph.
Section 1
Content for section 1.
Item 1
Item 2
print("Hello")
Important quote
Check out this link
```

**Special notes:**
- Hyperlinks lost
- Formatting info lost
- Pure content only
- Good for search and summarization

### 3. JSON Conversion

**Goal**: Structured data for programmatic processing

```json
{
  "url": "https://example.com",
  "title": "Main Title",
  "headings": [
    {"level": "h1", "text": "Main Title"},
    {"level": "h2", "text": "Section 1"}
  ],
  "paragraphs": [
    "Introduction paragraph.",
    "Content for section 1."
  ],
  "links": [
    {
      "text": "this link",
      "url": "https://example.com"
    }
  ]
}
```

**Special notes:**
- Structured format
- Elements categorized
- Relative URLs converted to absolute
- Good for programmatic processing
- Schema-based data extraction

### 4. XML Conversion

**Goal**: Standard markup format

```xml
<?xml version="1.0" encoding="UTF-8"?>
<page>
  <url>https://example.com</url>
  <title>Main Title</title>
  <heading level="h1">Main Title</heading>
  <heading level="h2">Section 1</heading>
  <paragraph>Introduction paragraph.</paragraph>
  <paragraph>Content for section 1.</paragraph>
  <link href="https://example.com">this link</link>
</page>
```

**Special notes:**
- Standard XML format
- Entity escaping:
  - &amp; (ampersand)
  - &lt; (angle brackets)
  - &quot; (quotes)
- XPath extraction possible
- Enterprise system compatible

### 5. HTML Format (Original)

**Goal**: Return original HTML

```python
# Input same as output
# No processing
```

**Use cases:**
- Display in web browser
- When original format needed
- For further processing

### PDF Processing

#### PDF Detection

```python
def is_pdf(response, url):
    # 1. Check Content-Type header
    content_type = response.headers.get("content-type")
    if content_type in ("application/pdf", "application/x-pdf"):
        return True
    
    # 2. Check URL extension
    if url.lower().endswith(".pdf"):
        return True
    
    # 3. Check file signature (magic bytes)
    if response.content.startswith(b"%PDF"):
        return True
    
    return False
```

#### PDF Text Extraction

```python
from pypdf import PdfReader
from io import BytesIO

pdf_bytes = response.content
reader = PdfReader(BytesIO(pdf_bytes))

# Extract metadata
title = reader.metadata.title

# Extract per-page text
pages = []
for page in reader.pages:
    text = page.extract_text() or ""
    pages.append(text.strip())

# Result
{
    "title": "PDF Title",
    "page_count": 42,
    "pages": [
        {"page": 1, "text": "Page 1 content..."},
        {"page": 2, "text": "Page 2 content..."},
        ...
    ],
    "text": "Concatenated text from all pages..."
}
```

#### PDF Format Conversion

**Markdown:**
```
# PDF Title

[Page 1]
Page 1 content...

[Page 2]
Page 2 content...
```

**JSON:**
```json
{
    "url": "https://example.com/document.pdf",
    "title": "PDF Title",
    "page_count": 42,
    "pages": [
        {"page": 1, "text": "..."},
        {"page": 2, "text": "..."}
    ],
    "text": "Full concatenated text..."
}
```

**XML:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<pdf>
    <url>https://example.com/document.pdf</url>
    <title>PDF Title</title>
    <page number="1">Page 1 text...</page>
    <page number="2">Page 2 text...</page>
</pdf>
```

---

## Metadata & Performance

### Fetch Result Metadata

```json
{
    "url": "https://example.com",
    "final_url": "https://example.com/redirected",
    "status": "success",
    "title": "Page Title",
    "content": "...",
    "format": "markdown",
    "latency_ms": 1250,
    "metadata": {
        "status_code": 200,
        "content_length": 5000,        // Processed content size
        "source_content_length": 25000, // Original HTML size
        "content_type": "text/html; charset=utf-8",
        "document_type": "html",       // or "pdf"
        "links_count": 42              // Links in HTML
    }
}
```

### Performance Optimization

1. **Parallel Processing**
   - batch_fetch: asyncio up to 10 concurrent requests
   - Result: ~5-10x faster than sequential

2. **Timeout Configuration**
   - Default: 30 seconds
   - Per-engine customizable
   - Prevents infinite hangs

3. **Resource Limits**
   - max_chars: content size limit
   - max_pages (crawl): prevent infinite loops
   - Semaphore: concurrent connection limits

4. **Caching (Optional)**
   - Response caching possible
   - URL-based result reuse

---

## Error Handling

### Common Error Scenarios

```python
# 1. URL validation failure
{
    "status": "error",
    "error": "URL is not allowed (invalid scheme, internal IP, or blocked hostname)"
}

# 2. Network error
{
    "status": "error",
    "error": "Connection timeout: Could not connect within 30.0s"
}

# 3. HTTP error
{
    "status": "failed",
    "error": "HTTP 404 Not Found"
}

# 4. Search engine error
{
    "engine": "google",
    "error": "HTTP 429 Too Many Requests (IP blocked)"
}
```

### Recovery Strategies

1. **Retry**
   - Recommended for transient errors
   - Client-side implementation

2. **Fallback**
   - Google blocked → use other engine
   - Failed single URL → try another

3. **Caching**
   - Reuse previous successful results
   - Prevent duplicate requests

---

## Security Considerations

### SSRF (Server-Side Request Forgery) Prevention

```python
def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)
    
    # 1. Validate scheme
    if not parsed.scheme or parsed.scheme not in ('http', 'https'):
        return False
    
    # 2. Validate hostname
    if not parsed.netloc:
        return False
    
    hostname = parsed.hostname or ''
    
    # 3. Block localhost
    blocked = {'localhost', '127.0.0.1', '::1', '0.0.0.0', '::'}
    if hostname in blocked:
        return False
    
    # 4. Block internal IPs
    if hostname.startswith(('192.168.', '10.')):
        return False
    
    return True
```

### XSS/Injection Prevention

- HTML content converted to markdown/text (not served raw)
- XML results have entity escaping
- JavaScript links (javascript:) excluded
- HTML entities properly decoded

---

## Comparison with SearXNG

### Overview

**SearXNG**: Open-source meta-search engine focused on privacy and user interface
**SemSearch**: MCP-based web search & data collection framework for LLM integration

Both use meta-search concepts but differ in architecture and purpose.

### Architecture Comparison

| Item | SemSearch | SearXNG |
|------|-----------|---------|
| **Deployment** | MCP server (programmatic API) | Web UI + REST API |
| **Primary Users** | AI/LLM systems | End users |
| **Interface** | JSON-RPC 2.0 (MCP) | Web browser, API |
| **Installation** | Python package | Docker, direct install |
| **Automation Level** | Very high (programmatic) | Medium (UI/API) |
| **Learning Curve** | Steep (MCP understanding needed) | Low (intuitive UI) |

### Functionality Comparison

#### 1. Search Engine Support

**SemSearch**:
- 9 engines: DuckDuckGo, Qwant, Startpage, Wikipedia, arXiv, Hacker News, GitHub, Bing, Google
- Custom parser per engine
- Easy to extend

**SearXNG**:
- 100+ search engines
- Dynamic engine loading
- Broader coverage
- Config file-based activation/deactivation

#### 2. Result Processing

**SemSearch**:
```
Search → Deduplicate → Domain filter → Simple scoring → Sort
```
- Structured metadata
- Uses engine scores
- Fast processing (O(n*m))

**SearXNG**:
```
Search → Apply weights → Deduplicate → Sort
```
- Per-engine trust weights
- More sophisticated scoring
- User-configurable

#### 3. Data Collection (Fetch/Crawl)

**SemSearch**:
- ✅ Single URL fetch (web_fetch)
- ✅ Multi-URL parallel (batch_fetch)
- ✅ Website crawling (crawl)
- ✅ PDF handling
- ✅ Multi-format conversion (Markdown, JSON, XML, Text)
- **Key advantage**: Integrated search + collection

**SearXNG**:
- ❌ Meta-search only
- No data collection capability
- Returns result links only

#### 4. Format Conversion

**SemSearch**:
- Markdown (preserves structure)
- Plain Text
- JSON (structured)
- XML (standard)
- HTML (original)

**SearXNG**:
- JSON
- RDF
- CSV

### Use Cases

#### SemSearch is Best For

1. **AI/LLM System Integration**
   ```
   LLM Agent
      ↓
   SemSearch MCP Tool (search)
      ↓
   Auto-fetch top results
      ↓
   Convert to Markdown for LLM
   ```

2. **Programmatic Automation**
   ```python
   results = await search_service.search(
       query="python async",
       engines=["github", "stackoverflow"],
       limit=10
   )
   
   for result in results:
       content = await fetch_service.fetch(result.url, format="markdown")
   ```

3. **Data Collection Pipeline**
   - Search → Filter → Batch fetch → Process

4. **Multi-engine Meta-search**
   - Merge multiple engines
   - Domain filtering
   - Custom scoring

#### SearXNG is Best For

1. **Privacy-Focused Web Search**
   - Local hosting possible
   - Search history not saved
   - No user tracking

2. **End-User Search**
   - Web UI provided
   - Browser integration
   - Easy configuration

3. **Broad Engine Coverage**
   - 100+ engines
   - Per-engine customization
   - Auto-complete, suggestions

4. **Specific Engine Forcing**
   - Use only certain engines
   - Per-engine trust weights

### Technology Stack

**SemSearch**:
```
Language: Python 3.10+
Key Libraries:
  - httpx (async HTTP)
  - BeautifulSoup4 (HTML parsing)
  - Pydantic (data validation)
  - asyncio (parallel processing)
  - pypdf (PDF extraction)

Features:
  - Fully async
  - Lightweight dependencies
  - MCP standard compliant
```

**SearXNG**:
```
Language: Python 3.8+
Key Libraries:
  - Flask (web framework)
  - lxml (XML parsing)
  - httpx (HTTP client)
  - pycurl (alternative HTTP)

Features:
  - Web application architecture
  - Multiple HTTP backends
  - Extension plugin system
```

### Performance Comparison

| Item | SemSearch | SearXNG |
|------|-----------|---------|
| **Response Time** | Fast (parallel) | Medium (sequential) |
| **Memory Usage** | Low | Medium-High |
| **CPU Usage** | Low (async) | Medium-High |
| **Concurrent Requests** | Many (asyncio) | Limited |
| **Large-scale Crawling** | Optimal | Not suitable |

### Integration Scenario

#### SearXNG + SemSearch Combination

```
User (Web UI)
    ↓
SearXNG (100+ engines, web UI)
    ↓
Extract results JSON
    ↓
SemSearch (Fetch + format conversion)
    ↓
Generate Markdown content
    ↓
LLM Analysis
```

**Benefits**:
- SearXNG's broad engine coverage
- SemSearch's auto-fetch capability
- Web UI + programmatic API

#### SemSearch Standalone (LLM-focused)

```
LLM Agent
    ↓
SemSearch web_search (optimized engines)
    ↓
SemSearch batch_fetch (parallel)
    ↓
SemSearch sem_search (integrated)
    ↓
Markdown results → LLM analysis
```

**Benefits**:
- Complete automation
- Integrated pipeline
- Maximum performance

### Decision Matrix

**Use SemSearch if you:**
- ✅ Integrate with AI/LLM systems
- ✅ Need programmatic automation
- ✅ Want search + data collection
- ✅ Need multiple format conversion
- ✅ Require high-performance parallel processing

**Use SearXNG if you:**
- ✅ Want privacy-focused web search
- ✅ Need end-user web UI
- ✅ Want 100+ engine support
- ✅ Need local hosting
- ✅ Want browser integration

**Use Both if you:**
- SearXNG handles web UI for users
- SemSearch handles LLM automation
- Complementary use cases

---

## Conclusion

SemSearch is a powerful, specialized web search and data collection framework designed for LLM integration and automated information retrieval. Through its architecture, it provides:

1. **Multi-engine Support**: 9 optimized search engines covering different domains
2. **Parallel Processing**: Async operations for high performance
3. **Format Flexibility**: Markdown, JSON, XML, Text, HTML conversions
4. **Security**: SSRF prevention, internal IP blocking
5. **Integrated Workflow**: Search + auto-fetch in one pipeline
6. **Structured Data**: Rich metadata for each result

Compared to SearXNG (meta-search UI), SemSearch's strength lies in programmatic automation and LLM integration, while SearXNG excels at user-facing privacy-focused search with broader engine coverage.

For AI systems requiring reliable web search with automatic content extraction, SemSearch provides an optimal, production-ready solution.
