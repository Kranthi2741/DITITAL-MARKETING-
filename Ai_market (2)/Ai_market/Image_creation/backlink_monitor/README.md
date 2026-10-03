# Backlink and unlinked-mention monitor

This standalone tool searches Google and Google News, fetches each article, checks for CEO/company mentions, and detects whether the article links to the company website.

```powershell
cd backlink_monitor
copy .env.example .env
pip install -r requirements.txt
python backlinks.py
```

The default range is `2026-08-25` through `2026-09-30`. You can change it without editing the code:

```powershell
python backlinks.py --start-date 2026-08-25 --end-date 2026-09-30
```

Important outputs:

- `unlinked_mentions.csv`: articles mentioning the CEO/company without a company URL
- `existing_backlinks.csv`: articles that already link to the company URL
- `review_mentions.csv`: possible matches requiring manual review
- `all_mentions.csv`: complete classified output

This uses search-engine discovery, so it cannot guarantee every page on the internet. Respect each site’s terms, robots rules, and rate limits.

Known URLs can be added to `seed_urls.txt`, one URL per line. Seed URLs are analyzed even when Google does not return them in search results.
