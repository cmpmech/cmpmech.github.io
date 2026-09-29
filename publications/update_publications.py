"""Collect journal publications from Google Scholar and Zenodo and render them into index.html.

    python3 publications/update_publications.py                # crawl, merge, render
    python3 publications/update_publications.py --render-only  # only rebuild the pages

Hand-edited files next to this script:
    scholars.csv      People to crawl (name, scholar_id, zenodo_name as "Last, First").
    publications.csv  One row per journal article. The script fills doi, title, journal and
                      year when empty and refreshes citations. You own category, summary and
                      status (empty = apply rule, "include" = always show, "exclude" = never).
                      code and data hold Zenodo links (several separated by spaces). The
                      script fills them from Zenodo when empty; "-" means none, never fill.

A paper is shown if it is published in MIN_YEAR or later or has more than MIN_CITATIONS
citations, unless status overrides this.
"""

import argparse
import csv
import datetime
import difflib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHOLARS_CSV = HERE / "scholars.csv"
PUBLICATIONS_CSV = HERE / "publications.csv"
CACHE_JSON = HERE / "crossref_cache.json"
INDEX_HTML = HERE.parent / "index.html"
PAGES = [INDEX_HTML, *sorted((HERE.parent / "research").glob("*.html"))]
TOPICS_DIR = HERE.parent / "research" / "topics"  # sections shared between pages

MIN_YEAR = datetime.date.today().year - 4
MIN_CITATIONS = 50
# Venues Crossref files as journal articles that are proceedings or preprints
NON_JOURNALS = ("Proceedings in Applied Mathematics", "Procedia", "SSRN")
CATEGORIES = ["discretization", "inverse", "am", "sciml"]
FIELDS = ["doi", "title", "journal", "year", "citations", "category", "summary", "status",
          "code", "data"]
ZENODO_COLUMNS = {"software": "code", "dataset": "data"}

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CROSSREF_MAILTO = ""  # optional contact address for Crossref's polite pool
CROSSREF_AGENT = "cmpmech-publications/1.0 (https://github.com/cmpmech)"


def fetch(url, user_agent=USER_AGENT):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            time.sleep(int(error.headers.get("Retry-After") or 0) or 2 ** (attempt + 1))


def strip_tags(text):
    return html.unescape(re.sub(r"<.*?>", "", text)).strip()


def normalize(text):
    text = unicodedata.normalize("NFKD", strip_tags(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def shown(row):
    if row["status"] in ("include", "exclude"):
        return row["status"] == "include"
    return int(row["year"] or 0) >= MIN_YEAR or int(row["citations"] or 0) > MIN_CITATIONS


# ---------------------------------------------------------------- Google Scholar

def crawl_scholar(scholar_id):
    """Return a list of dicts with title, venue, year and citations for one profile."""
    entries = []
    for start in range(0, 2000, 100):
        url = (f"https://scholar.google.com/citations?user={scholar_id}&hl=en"
               f"&cstart={start}&pagesize=100&sortby=pubdate")
        page = fetch(url)
        rows = re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', page, re.S)
        if start == 0 and not rows:
            sys.exit(f"Scholar returned no publications for {scholar_id} "
                     "(blocked or captcha?). Try again later.")
        for row in rows:
            gray = re.findall(r'<div class="gs_gray">(.*?)</div>', row, re.S)
            citations = re.search(r'class="gsc_a_ac gs_ibl">(\d*)<', row)
            year = re.search(r'gsc_a_h gsc_a_hc gs_ibl">(\d*)<', row)
            entries.append({
                "title": strip_tags(re.search(r'class="gsc_a_at">(.*?)</a>', row).group(1)),
                "venue": strip_tags(gray[1]) if len(gray) > 1 else "",
                "year": int(year.group(1) or 0) if year else 0,
                "citations": int(citations.group(1) or 0) if citations else 0,
            })
        if len(rows) < 100:
            break
        time.sleep(2.5)
    return entries


# ---------------------------------------------------------------- Crossref

def crossref_record(item):
    date = item.get("published-print") or item.get("issued") or {}
    year = (date.get("date-parts") or [[None]])[0][0]
    title = (item.get("title") or [""])[0]
    title = re.sub(r"<(/?)i>", r"<\1em>", title)
    title = re.sub(r"<(?!/?em>).*?>", "", title)
    return {
        "doi": item["DOI"].lower(),
        "type": item.get("type", ""),
        "title": " ".join(title.split()),
        "journal": html.unescape((item.get("container-title") or [""])[0]),
        "year": str(year or ""),
    }


def crossref_url(path, **params):
    if CROSSREF_MAILTO:
        params["mailto"] = CROSSREF_MAILTO
    return f"https://api.crossref.org/{path}?" + urllib.parse.urlencode(params)


def same_title(scholar_title, crossref_title):
    a, b = normalize(scholar_title), normalize(crossref_title)
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
        return True
    # Scholar truncates long titles and sometimes appends author names
    return min(len(a), len(b)) >= 30 and (a.startswith(b) or b.startswith(a))


def is_journal(record):
    return (record["type"] == "journal-article" and not record["doi"].startswith("10.2139/")
            and not any(name in record["journal"] for name in NON_JOURNALS))


def crossref_search(title, surname):
    """Best Crossref match for a Scholar title by the given author, or None."""
    url = crossref_url("works", **{"query.bibliographic": title, "query.author": surname,
                                   "rows": 20, "select": "DOI,type,title,container-title,"
                                                         "author,published-print,issued"})
    matches = []
    for item in json.loads(fetch(url, CROSSREF_AGENT))["message"]["items"]:
        authors = {normalize(a.get("family", "")) for a in item.get("author", [])}
        if same_title(title, (item.get("title") or [""])[0]) and surname in authors:
            matches.append(crossref_record(item))
    # Prefer the journal version over preprints or proceedings with the same title
    matches.sort(key=lambda m: not is_journal(m))
    return matches[0] if matches else None


def crossref_doi(doi):
    return crossref_record(json.loads(fetch(crossref_url(f"works/{doi}"), CROSSREF_AGENT))["message"])


# ---------------------------------------------------------------- Zenodo

def crawl_zenodo(creator):
    """Return the software and dataset records (latest versions) of one Zenodo creator."""
    records = []
    for page in range(1, 41):
        url = "https://zenodo.org/api/records?" + urllib.parse.urlencode(
            {"q": f'creators.name:"{creator}"', "size": 25, "page": page})
        hits = json.loads(fetch(url, CROSSREF_AGENT))["hits"]["hits"]
        for hit in hits:
            metadata = hit["metadata"]
            column = ZENODO_COLUMNS.get(metadata["resource_type"]["type"])
            if column is None:
                continue
            concept = hit.get("conceptdoi")
            records.append({
                "id": hit.get("conceptrecid") or str(hit["id"]),
                "column": column,
                "title": metadata["title"],
                "url": f"https://doi.org/{concept}" if concept else hit["links"]["self_html"],
                "related": {r["identifier"].lower().removeprefix("https://doi.org/")
                            for r in metadata.get("related_identifiers", [])},
            })
        if len(hits) < 25:
            break
        time.sleep(1)
    return records


def zenodo_paper(record, rows):
    """DOI of the paper a Zenodo record belongs to, or None."""
    for doi in record["related"]:
        if doi in rows:
            return doi
    # Zenodo titles are usually the paper title plus e.g. "[Software]" or "Source code of"
    title = re.sub(r"\[.*?\]|\(.*?\)", "", record["title"])
    title = re.sub(r"^(source code|code|data|dataset)( of| for)?\s*[:-]?\s*", "", title, flags=re.I)
    for doi, row in rows.items():
        if same_title(title, row["title"]):
            return doi
    return None


# ---------------------------------------------------------------- CSV

def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_publications(rows):
    rows.sort(key=lambda r: (-int(r["year"] or 0), r["title"].lower()))
    with open(PUBLICATIONS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------- update

def update():
    rows = {r["doi"].lower(): {**dict.fromkeys(FIELDS, ""), **r, "doi": r["doi"].lower()}
            for r in read_csv(PUBLICATIONS_CSV)} if PUBLICATIONS_CSV.exists() else {}
    cache = json.loads(CACHE_JSON.read_text()) if CACHE_JSON.exists() else {}
    citations, unresolved = {}, []

    for scholar in read_csv(SCHOLARS_CSV):
        print(f"Crawling {scholar['name']} ...")
        surname = normalize(scholar["name"]).split()[-1]
        for entry in crawl_scholar(scholar["scholar_id"]):
            # Only look up candidates; one year of slack for preprint/print year mismatch
            if entry["year"] < MIN_YEAR - 1 and entry["citations"] <= MIN_CITATIONS:
                continue
            key = normalize(entry["title"])
            if key not in cache:
                cache[key] = crossref_search(entry["title"], surname)
                CACHE_JSON.write_text(json.dumps(cache, indent=1, sort_keys=True))
                time.sleep(1)
            record = cache[key]
            if record is None:
                unresolved.append(entry)
                continue
            if not is_journal(record):
                continue
            doi = record["doi"]
            citations[doi] = max(citations.get(doi, 0), entry["citations"])
            rows.setdefault(doi, {**dict.fromkeys(FIELDS, ""), "doi": doi})
            for field in ("title", "journal", "year"):
                rows[doi][field] = rows[doi][field] or record[field]

    for doi, row in rows.items():
        if doi in citations:
            row["citations"] = str(citations[doi])
        if not (row["title"] and row["journal"] and row["year"]):  # rows added by hand
            record = crossref_doi(doi)
            if not is_journal(record):
                print(f"warning: {doi} is not a journal article ({record['type']})")
            for field in ("title", "journal", "year"):
                row[field] = row[field] or record[field]

    unlinked, seen = [], set()
    for scholar in read_csv(SCHOLARS_CSV):
        if not scholar.get("zenodo_name"):
            continue
        print(f"Searching Zenodo for {scholar['zenodo_name']} ...")
        for record in crawl_zenodo(scholar["zenodo_name"]):
            if record["id"] in seen:
                continue
            seen.add(record["id"])
            if any(record["url"] in r[c].split() for r in rows.values() for c in ("code", "data")):
                continue
            doi = zenodo_paper(record, rows)
            if doi is None:
                unlinked.append(record)
            elif not rows[doi][record["column"]]:
                rows[doi][record["column"]] = record["url"]
            elif rows[doi][record["column"]] != "-":
                unlinked.append(record)  # the paper already has a different link

    write_publications(list(rows.values()))

    if unlinked:
        print("\nZenodo records not linked to any paper (add the URL to the code or data "
              "column of the right row):")
        for record in unlinked:
            print(f"  {record['column']:4}  {record['url']}  {record['title']}")

    missing = [r for r in rows.values() if shown(r) and not (r["category"] and r["summary"])]
    if missing:
        print("\nShown papers without category or summary (edit publications.csv):")
        for r in missing:
            print(f"  {r['doi']}  {strip_tags(r['title'])}")
    unresolved = {normalize(e["title"]): e for e in unresolved
                  if e["year"] >= MIN_YEAR or e["citations"] > MIN_CITATIONS}.values()
    if unresolved:
        print("\nScholar entries matching the rule but not found on Crossref "
              "(add them by DOI if they are journal articles):")
        for e in unresolved:
            print(f"  {e['year']} [{e['citations']}]  {e['title']}  ({e['venue']})")


# ---------------------------------------------------------------- render

def paper_item(r, indent, compact=False):
    links = [f"<a href=\"{html.escape(url)}\">{label}</a>"
             for column, label in (("code", "Code"), ("data", "Data"))
             for url in r[column].split() if url != "-"]
    title = f"<a href=\"https://doi.org/{r['doi']}\">{r['title']}</a>"
    if compact:
        links = f" <span class=\"pub-links\">{' · '.join(links)}</span>" if links else ""
        return f"{indent}<li>{title}{links}</li>\n"
    lines = [f"<li>",
             f"  {title}",
             f"  <span class=\"meta\">{html.escape(r['journal'])}, {r['year']}</span>"]
    if r["summary"]:
        lines.append(f"  <p>{r['summary']}</p>")
    if links:
        lines.append(f"  <span class=\"pub-links\">{' · '.join(links)}</span>")
    lines.append("</li>")
    return "".join(f"{indent}{line}\n" for line in lines)


def render():
    """Fill every <!-- papers: ... --> ... <!-- /papers --> block in the site's pages.

    "<!-- papers: category=sciml -->" lists the shown papers of a category, newest first.
    "<!-- papers: 10.1/abc 10.2/def -->" lists exactly these papers, in this order.
    A leading "compact" ("<!-- papers: compact 10.1/abc -->") shows only titles and links.
    "<!-- topic: name --> ... <!-- /topic -->" is first replaced by research/topics/name.html,
    so a section used on several pages is written once.
    """
    rows = {r["doi"].lower(): {**dict.fromkeys(FIELDS, ""), **r}
            for r in read_csv(PUBLICATIONS_CSV)}
    for row in rows.values():
        if shown(row) and row["category"] not in CATEGORIES:
            print(f"warning: not shown, category '{row['category']}' is not one of "
                  f"{', '.join(CATEGORIES)}: {row['doi']}  {strip_tags(row['title'])[:60]}")

    def select(spec, page):
        if spec.startswith("category="):
            category = spec.removeprefix("category=")
            return sorted((r for r in rows.values() if shown(r) and r["category"] == category),
                          key=lambda r: (-int(r["year"] or 0), -int(r["citations"] or 0)))
        for doi in spec.lower().split():
            if doi not in rows:
                sys.exit(f"{page.name}: {doi} is not in {PUBLICATIONS_CSV.name}")
        return [rows[doi] for doi in spec.lower().split()]

    def include(match):
        indent, name = match.group(1), match.group(2).strip()
        source = TOPICS_DIR / f"{name}.html"
        if not source.exists():
            sys.exit(f"{page.name}: topic {name} not found ({source})")
        body = "".join(indent + line if line.strip() else line
                       for line in source.read_text(encoding="utf-8").splitlines(True))
        return f"{indent}<!-- topic: {name} -->\n{body}{indent}<!-- /topic -->"

    topics = re.compile(r"^([ \t]*)<!-- topic: (.*?) -->\n.*?^[ \t]*<!-- /topic -->", re.S | re.M)
    pattern = re.compile(r"^([ \t]*)<!-- papers: (.*?) -->\n.*?^[ \t]*<!-- /papers -->",
                         re.S | re.M)
    for page in PAGES:
        text = topics.sub(include, page.read_text(encoding="utf-8"))
        def fill(match):
            indent, spec = match.groups()
            compact = spec.startswith("compact ")
            papers = select(spec.removeprefix("compact ").strip(), page)
            items = "".join(paper_item(r, indent, compact) for r in papers)
            return f"{indent}<!-- papers: {spec} -->\n{items}{indent}<!-- /papers -->"
        text, count = pattern.subn(fill, text)
        page.write_text(text, encoding="utf-8")
        print(f"{page.relative_to(HERE.parent)}: {count} paper lists")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--render-only", action="store_true",
                        help="skip crawling, only rebuild the pages from publications.csv")
    if not parser.parse_args().render_only:
        update()
    render()
