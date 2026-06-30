#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

class DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_snippet = False
        self.current_title = None
        self.current_url = None
        self.current_snippet = None
        self.results = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(str(attrs.get("class", "")).split())
        if tag == "a" and ("result__a" in classes or "result-link" in classes):
            self.in_title = True
            self.current_title = ""
            self.current_url = self._decode_ddg_url(attrs.get("href", ""))
        elif (
            ("result__snippet" in classes and tag in ("a", "td"))
            or ("result-snippet" in classes and tag == "td")
        ):
            self.in_snippet = True
            self.current_snippet = ""

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_title = False
            if self.in_snippet:
                self._finish_result()
                self.in_snippet = False
        elif tag == "td" and self.in_snippet:
            self._finish_result()
            self.in_snippet = False

    def handle_data(self, data):
        if self.in_title:
            self.current_title += data
        elif self.in_snippet:
            self.current_snippet += data

    def _decode_ddg_url(self, href):
        href = str(href or "")
        if href.startswith("//"):
            href = "https:" + href
        try:
            parsed = urllib.parse.urlparse(href)
            query = urllib.parse.parse_qs(parsed.query)
            if "uddg" in query and query["uddg"]:
                return query["uddg"][0]
        except Exception:
            pass
        return href

    def _finish_result(self):
        if self.current_title and self.current_snippet:
            self.results.append({
                "title": self.current_title.strip(),
                "url": self.current_url or "",
                "snippet": self.current_snippet.strip(),
            })
        self.current_title = None
        self.current_url = None
        self.current_snippet = None

def _clean(value):
    return " ".join(str(value or "").split())

def _tavily_base_url():
    return os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com").rstrip("/")

def tavily_search(query, max_results=10):
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []

    count = max(1, min(20, int(max_results or 10)))
    payload = {
        "query": query,
        "max_results": count,
    }
    if os.environ.get("TAVILY_INCLUDE_ANSWER", "").lower() in ("1", "true", "yes"):
        payload["include_answer"] = True
    if os.environ.get("TAVILY_SEARCH_DEPTH"):
        payload["search_depth"] = os.environ["TAVILY_SEARCH_DEPTH"]
    if os.environ.get("TAVILY_TOPIC"):
        payload["topic"] = os.environ["TAVILY_TOPIC"]

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _tavily_base_url() + "/search",
        data=data,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "pettaclaw-websearch/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8"))

    results = []
    for item in body.get("results", [])[:count]:
        results.append({
            "title": _clean(item.get("title")),
            "url": _clean(item.get("url")),
            "snippet": _clean(item.get("content") or item.get("snippet")),
        })
    if body.get("answer"):
        results.insert(0, {
            "title": "Tavily answer",
            "url": "",
            "snippet": _clean(body.get("answer")),
        })
    return results[:count]

def ddg_search(query, max_results=10):
    results = []
    for base in (
        "https://lite.duckduckgo.com/lite/?q=",
        "https://html.duckduckgo.com/html/?q=",
    ):
        url = base + urllib.parse.quote_plus(query)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")

        parser = DDGParser()
        parser.feed(html)
        results = parser.results[:max_results]
        if results:
            break
    return [
        {
            "title": _clean(r.get("title")),
            "url": _clean(r.get("url")),
            "snippet": _clean(r.get("snippet")),
        }
        for r in results
    ]

def _provider_from_query(query):
    text = str(query or "").strip()
    lower = text.lower()
    for prefix, provider in (
        ("tavily:", "tavily"),
        ("ddg:", "ddg"),
        ("duckduckgo:", "ddg"),
        ("auto:", "auto"),
    ):
        if lower.startswith(prefix):
            return provider, text[len(prefix):].strip()
    return os.environ.get("METTACLAW_SEARCH_PROVIDER", "auto").strip().lower(), text

def search_(query, max_results=10):
    provider, query = _provider_from_query(query)
    if provider in ("tavily", "api"):
        return tavily_search(query, max_results)
    if provider in ("ddg", "duckduckgo", "html"):
        return ddg_search(query, max_results)

    try:
        results = tavily_search(query, max_results)
        if results:
            return results
    except Exception:
        pass
    return ddg_search(query, max_results)

def _format_results(results):
    ret = "("
    for r in results:
        url = (" URL: " + r["url"]) if r.get("url") else ""
        ret += "(TITLE: " + r["title"] + url + " SNIPPET: " + r["snippet"] + ") "
    ret += ")"
    return ret

def search(query, max_results=10):
    try:
        return _format_results(search_(query, max_results))
    except Exception:
        return ""

def search_tavily(query, max_results=10):
    try:
        return _format_results(tavily_search(query, max_results))
    except Exception:
        return ""

def search_ddg(query, max_results=10):
    try:
        return _format_results(ddg_search(query, max_results))
    except Exception:
        return ""
