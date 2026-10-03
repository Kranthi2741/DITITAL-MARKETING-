"""Discover linked and unlinked company mentions from Google/Google News.

Required environment variables: SERPAPI_KEY, CEO_NAME, COMPANY_NAME, COMPANY_URL.
Run from this folder with: python backlinks.py
"""
import os
import re
import time
import argparse
import json
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from serpapi import GoogleSearch

try:
    import trafilatura
except ImportError:
    trafilatura = None

load_dotenv()

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
CEO_NAME = os.getenv("CEO_NAME", "Vamsi Karatam")
COMPANY_NAME = os.getenv("COMPANY_NAME", "proRITHM")
LEGAL_NAME = os.getenv("LEGAL_NAME", "DeepFacts Private Limited")
COMPANY_URL = os.getenv("COMPANY_URL", "https://prorithm.com")
COMPANY_DOMAIN = urlparse(COMPANY_URL).netloc.lower().removeprefix("www.")
SEED_URLS_FILE = "seed_urls.txt"

CEO_VARIATIONS = [CEO_NAME, "Vamsi Krishna Karatam", "Venkata Vamsi Krishna Karatam"]
COMPANY_VARIATIONS = [COMPANY_NAME, "proRithm", "Prorithm", LEGAL_NAME, "DeepFacts Pvt Ltd"]
SEARCH_QUERIES = list(dict.fromkeys(
    [f'"{name}" {company}' for name in CEO_VARIATIONS for company in COMPANY_VARIATIONS]
    + [f'"{name}"' for name in CEO_VARIATIONS]
    + [f'"{name}" healthcare' for name in COMPANY_VARIATIONS]
))

EXCLUDED_DOMAINS = {"facebook.com", "instagram.com", "linkedin.com", "youtube.com", "spotify.com", "twitter.com", "x.com", "naukri.com", "indeed.com", "indiamart.com", "crunchbase.com", "f6s.com"}
EXCLUDED_PATHS = ("/tag/", "/category/", "/search", "/profile", "/author/", "/jobs/", "/careers/", "/lyrics/", "/playlist/", "/login", "/signup")
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (compatible; BacklinkMonitor/1.0)"


def normalize(value):
    return re.sub(r"\s+", " ", value or "").strip()


def excluded(url):
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")
    return domain in EXCLUDED_DOMAINS or any(part in parsed.path.lower() for part in EXCLUDED_PATHS)


def search(query, engine, start_date, end_date):
    date_filter = f"after:{start_date.isoformat()} before:{end_date.isoformat()}"
    full_query = f"{query} {date_filter}"
    data = GoogleSearch({"engine": engine, "q": full_query, "api_key": SERPAPI_KEY, "num": 20, "hl": "en", "gl": "in", "tbs": f"cdr:1,cd_min:{start_date.strftime('%m/%d/%Y')},cd_max:{end_date.strftime('%m/%d/%Y')}"}).get_dict()
    key = "news_results" if engine == "google_news" else "organic_results"
    return [{"url": item.get("link", ""), "search_title": item.get("title", ""), "query": query, "source": engine}
            for item in data.get(key, []) if item.get("link")]


def parse_date(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value[:40], fmt).date()
            except ValueError:
                continue
    return None


def fetch_article(url):
    response = session.get(url, timeout=25, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title = normalize((soup.find("h1") or soup.find("title")).get_text(" ", strip=True) if (soup.find("h1") or soup.find("title")) else "")
    published_date = None
    for selector in ('meta[property="article:published_time"]', 'meta[name="date"]', 'meta[itemprop="datePublished"]', 'time[datetime]'):
        tag = soup.select_one(selector)
        published_date = parse_date(tag.get("content") or tag.get("datetime") or tag.get_text()) if tag else None
        if published_date:
            break
    if not published_date:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.string or "")
                candidates = payload if isinstance(payload, list) else [payload]
                published_date = next((parse_date(item.get("datePublished")) for item in candidates if isinstance(item, dict) and item.get("datePublished")), None)
                if published_date:
                    break
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
    links = [(urljoin(response.url, tag.get("href")), normalize(tag.get_text(" ", strip=True))) for tag in soup.find_all("a", href=True)]
    text = trafilatura.extract(response.text, favor_precision=True) if trafilatura else ""
    if not text:
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup.body
        text = article.get_text(" ", strip=True) if article else ""
    return response.url, title, normalize(text), links, published_date


def contains(text, values):
    lower = text.lower()
    return [value for value in values if value.lower() in lower]


def company_link(links):
    targets = []
    for href, anchor in links:
        domain = urlparse(href).netloc.lower().removeprefix("www.")
        if domain == COMPANY_DOMAIN or domain.endswith("." + COMPANY_DOMAIN):
            targets.append({"url": href, "anchor": anchor})
    return targets


def classify(url, title, text, links):
    combined = f"{title} {text}"
    ceo_matches = contains(combined, CEO_VARIATIONS)
    company_matches = contains(combined, COMPANY_VARIATIONS)
    linked = company_link(links)
    score = (4 if ceo_matches else 0) + (5 if company_matches else 0)
    healthcare = any(term in combined.lower() for term in ("healthcare", "healthtech", "patient monitoring", "medical", "clinical", "digital health", "ecg"))
    score += 2 if healthcare else 0
    if excluded(url):
        classification = "IRRELEVANT"
        reason = "Excluded social, directory, job, or utility URL"
    elif ceo_matches and company_matches and score >= 9:
        classification = "RELEVANT_LINKED" if linked else "RELEVANT_UNLINKED"
        reason = "CEO and company mentioned; company URL found" if linked else "CEO and company mentioned; no company URL found"
    elif ceo_matches or company_matches:
        classification, reason = "REVIEW", "Only one entity or weak context matched"
    else:
        classification, reason = "IRRELEVANT", "No target entity found in article text"
    excerpt = ""
    match = re.search(r".{0,180}(?:" + "|".join(map(re.escape, CEO_VARIATIONS + COMPANY_VARIATIONS)) + r").{0,300}", combined, re.I)
    if match:
        excerpt = normalize(match.group(0))
    return {"title": title, "url": url, "ceo_matches": "; ".join(ceo_matches), "company_matches": "; ".join(company_matches), "company_link_found": bool(linked), "company_links": "; ".join(item["url"] for item in linked), "relevance_score": score, "classification": classification, "reason": reason, "excerpt": excerpt}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2026-08-25", help="Inclusive YYYY-MM-DD date")
    parser.add_argument("--end-date", default="2026-09-30", help="Inclusive YYYY-MM-DD date")
    args = parser.parse_args()
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    if end_date < start_date:
        raise SystemExit("--end-date must be on or after --start-date")
    print(f"Date range: {start_date} to {end_date}")
    if not SERPAPI_KEY:
        raise SystemExit("Set SERPAPI_KEY in backlink_monitor/.env before running.")
    discovered = {}
    if os.path.exists(SEED_URLS_FILE):
        with open(SEED_URLS_FILE, encoding="utf-8") as handle:
            for line in handle:
                url = line.strip()
                if url and not url.startswith("#"):
                    discovered[url] = {"url": url, "search_title": "Seed URL", "query": "seed_urls.txt", "source": "seed"}
        print(f"Loaded {len(discovered)} seed URL(s)")
    for index, query in enumerate(SEARCH_QUERIES, 1):
        print(f"[{index}/{len(SEARCH_QUERIES)}] {query}")
        for engine in ("google", "google_news"):
            try:
                for item in search(query, engine, start_date, end_date):
                    if not excluded(item["url"]):
                        discovered.setdefault(item["url"], item)
            except Exception as error:
                print(f"Search failed: {error}")
        time.sleep(0.5)
    rows = []
    for index, item in enumerate(discovered.values(), 1):
        print(f"Analyzing [{index}/{len(discovered)}] {item['url']}")
        try:
            final_url, title, text, links, published_date = fetch_article(item["url"])
            if published_date and not (start_date <= published_date <= end_date):
                continue
            row = classify(final_url, title, text, links)
            row.update({"published_date": published_date.isoformat() if published_date else "", "source": item["source"], "search_query": item["query"], "article_text_length": len(text), "status": "ANALYZED"})
        except Exception as error:
            row = {"title": item["search_title"], "url": item["url"], "classification": "REVIEW", "reason": str(error), "status": "FETCH_ERROR"}
        rows.append(row)
    frame = pd.DataFrame(rows)
    frame.to_csv("all_mentions.csv", index=False)
    frame[frame.classification.str.startswith("RELEVANT")].to_csv("relevant_mentions.csv", index=False)
    frame[frame.classification == "RELEVANT_UNLINKED"].to_csv("unlinked_mentions.csv", index=False)
    frame[frame.classification == "RELEVANT_LINKED"].to_csv("existing_backlinks.csv", index=False)
    frame[frame.classification == "REVIEW"].to_csv("review_mentions.csv", index=False)
    frame[frame.classification == "IRRELEVANT"].to_csv("irrelevant_mentions.csv", index=False)
    print(f"Finished: {len(frame)} articles; unlinked mentions: {(frame.classification == 'RELEVANT_UNLINKED').sum()}")


if __name__ == "__main__":
    main()
