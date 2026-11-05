"""Interactive THSC paper downloader. Python 3.10+, standard library only."""
import argparse
import base64
import csv
import gzip
import hashlib
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit, urlencode, parse_qs
from urllib.request import Request, urlopen

SITE = 'https://thsconline.github.io'
MIRROR = 'https://thsconline.pages.dev'
ROOT = Path(__file__).resolve().parent


def clean_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, quote(unquote(p.path), safe='/'), p.query, ''))


def fetch(url, timeout=45):
    request = Request(clean_url(url), headers={'User-Agent': 'THSC-Paper-Extractor/2.0'})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def site_fetch(url):
    errors = []
    for base in (SITE, MIRROR):
        candidate = base + urlsplit(url).path
        try:
            return fetch(candidate)
        except Exception as error:
            errors.append(f'{candidate}: {error}')
    raise RuntimeError('; '.join(errors))


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.current = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = [dict(attrs), '']
        elif tag == 'br' and self.current:
            self.current[1] += ' '

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            attrs, label = self.current
            self.links.append((attrs, ' '.join(label.split())))
            self.current = None


def page_links(url):
    return Links(site_fetch(url).decode('utf-8-sig')).links


def children(url, folders_only=False):
    prefix = unquote(urlsplit(url).path)
    found = {}
    for attrs, title in page_links(url):
        href = attrs.get('href', '')
        target = clean_url(urljoin(url, href))
        p = urlsplit(target)
        path = unquote(p.path)
        if p.netloc != urlsplit(SITE).netloc or not path.startswith(prefix) or path == prefix:
            continue
        relative = path[len(prefix):]
        if relative in ('index.html', '') or href.startswith('#'):
            continue
        if folders_only:
            if '/' not in relative.rstrip('/') and not Path(relative).suffix:
                found[target.rstrip('/') + '/'] = relative.strip('/')
        elif not Path(path).suffix or path.endswith(('.html', '.htm')):
            found[target if Path(path).suffix else target.rstrip('/') + '/'] = title or relative
    return [(label, target) for target, label in found.items()]


@dataclass(frozen=True)
class Paper:
    title: str
    collection: str
    url: str
    page: str

    @property
    def key(self):
        return self.collection + ':' + self.title if self.collection else self.url


def papers_on(url, links):
    result = []
    for attrs, title in links:
        match = re.search(r'pdfa?\(\s*this\s*,\s*[\'"]?(\d+)', attrs.get('onclick', ''), re.I)
        target = clean_url(urljoin(url, attrs.get('href', '')))
        route = re.search(r'/s/[vd]/(\d+)/(.+)', unquote(urlsplit(target).path))
        if match or route:
            collection = match[1] if match else route[1]
            name = title if match else route[2]
            # Match the public viewer's title normalization.
            name = re.sub(r'[^A-Za-z0-9._\- ]', '', name).strip()
            result.append(Paper(name, collection, '', url))
        elif urlsplit(target).path.lower().endswith('.pdf') or '/s/em/' in target:
            result.append(Paper(title or unquote(urlsplit(target).path.rsplit('/', 1)[-1]), '', target, url))
    return result


def scan(url, log=print):
    """Crawl only pages within the chosen subject/category, never the whole web."""
    scope = unquote(urlsplit(url).path)
    single = bool(Path(scope).suffix)
    queue, visited, papers, errors = [url], set(), {}, []
    while queue:
        current = queue.pop(0)
        canonical = current.split('?', 1)[0].removesuffix('index.html')
        if canonical in visited:
            continue
        visited.add(canonical)
        log('Scanning ' + unquote(current))
        try:
            links = page_links(current)
        except Exception as error:
            errors.append({'Page': current, 'Error': str(error)})
            continue
        for paper in papers_on(current, links):
            papers.setdefault(paper.key, paper)
        if single:
            continue
        for attrs, _ in links:
            href = attrs.get('href', '')
            target = clean_url(urljoin(current, href))
            p = urlsplit(target)
            if (not href or href.startswith('#') or p.netloc != urlsplit(SITE).netloc
                    or not unquote(p.path).startswith(scope)):
                continue
            if not Path(p.path).suffix or p.path.endswith(('.html', '.htm')):
                queue.append(target if Path(p.path).suffix else target.rstrip('/') + '/')
    return list(papers.values()), errors


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip().rstrip(' .')[:110]
    if not name or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}:
        name = '_' + name
    return name


def relative_path(paper):
    parts = unquote(urlsplit(paper.page).path).strip('/').split('/')
    year = parts[1] if len(parts) > 1 else 'papers'
    subject = parts[2] if len(parts) > 2 else 'General'
    category = Path(parts[-1]).stem if Path(parts[-1]).suffix else 'papers'
    suffix = hashlib.sha256(paper.key.encode()).hexdigest()[:10]
    return Path(safe_name(year), safe_name(subject), safe_name(category), safe_name(paper.title.removesuffix('.pdf')) + f' [{suffix}].pdf')


def valid_pdf(data):
    return data.startswith(b'%PDF-') and b'%%EOF' in data[-4096:]


def direct_url(url):
    url = urljoin(SITE, url)
    p = urlsplit(url)
    if p.path.startswith('/s/em/'):
        path = p.path[len('/s/em'):]
        if not path.lower().endswith('.pdf'):
            path += '.pdf'
        return urlunsplit((p.scheme, p.netloc, path, '', ''))
    if '/viewer.html' in p.path and 'file' in parse_qs(p.query):
        return urljoin(url, parse_qs(p.query)['file'][0])
    return url


class Downloader:
    def __init__(self, rounds=2, log=print):
        self.rounds, self.log = rounds, log
        self.indexes = {}
        self.workers = None

    def worker_urls(self, paper):
        if self.workers is None:
            js = site_fetch(SITE + '/s/viewer.js').decode('utf-8-sig')
            block = js.split('function selectworker', 1)[-1].split('function getUrlParameter', 1)[0]
            self.workers = list(dict.fromkeys(re.findall(r'[\'"](AKfy[\w-]+)[\'"]', block)))
        query = urlencode(dict(export='view', base=paper.collection, field=paper.title,
                               hash=hashlib.sha256(paper.collection.encode()).hexdigest()))
        return [f'https://script.google.com/macros/s/{worker}/exec?{query}' for worker in self.workers]

    def mirrors(self, paper):
        if not paper.collection:
            urls = [direct_url(paper.url)]
        else:
            if paper.collection not in self.indexes:
                try:
                    self.indexes[paper.collection] = json.loads(site_fetch(SITE + f'/s/index/{paper.collection}.json'))
                except Exception:
                    self.indexes[paper.collection] = {}
            resources = self.indexes[paper.collection].get(paper.title, [])
            if isinstance(resources, dict):
                resources = [resources]
            urls = [direct_url(r['url']) for r in resources if isinstance(r, dict) and r.get('url')]
            urls = [u for u in urls if '/s/v/' not in u and '/s/d/' not in u]
        for url in list(urls):
            if url.startswith(SITE + '/'):
                urls.append(MIRROR + url[len(SITE):])
        return list(dict.fromkeys(urls))

    def primary(self, paper):
        path = quote(paper.collection, safe='') + '/' + quote(paper.title, safe='')
        root = 'https://www.thsconline.net/api/v1/'
        meta = json.loads(fetch(root + 'getmetadata/' + path))
        count = meta.get('fragmentCount')
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10000:
            raise ValueError(str(meta.get('error', 'Invalid fragment count')))
        fragments = [fetch(root + 'getfragment/' + path + f'/{i}') for i in range(count)]
        return gzip.decompress(b''.join(fragments))

    def download(self, paper, output):
        relative = relative_path(paper)
        target = output / relative
        row = dict(Paper=paper.title, Collection=paper.collection, Status='Failed', File=relative.as_posix(), Source='', Error='')
        if target.is_file() and valid_pdf(target.read_bytes()):
            row['Status'] = 'Already downloaded'
            return row
        errors = []
        candidates = [('Direct mirror', url) for url in self.mirrors(paper)]
        if paper.collection:
            candidates.insert(0, ('Primary API', ''))
            try:
                candidates.extend(('Google mirror', u) for u in self.worker_urls(paper))
            except Exception as error:
                errors.append('Mirror discovery: ' + str(error))
        for attempt in range(self.rounds):
            for label, url in candidates:
                try:
                    data = self.primary(paper) if label == 'Primary API' else fetch(url)
                    if label == 'Google mirror':
                        payload = json.loads(data)
                        if payload.get('error'):
                            raise ValueError(str(payload['error']))
                        data = base64.b64decode(payload['data'], validate=True)
                    if not valid_pdf(data):
                        raise ValueError('Response is not a complete PDF')
                except Exception as error:
                    errors.append(f'{label} {url}: {error}')
                    self.log(f'  {label} failed for {paper.title}; trying next source ({error})')
                    continue
                # Filesystem failures must not cause repeat network downloads.
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix('.pdf.part')
                temporary.write_bytes(data)
                temporary.replace(target)
                row.update(Status='Downloaded', Source=url or 'https://www.thsconline.net/api/v1/', Error='')
                return row
            if attempt + 1 < self.rounds:
                time.sleep(min(2 ** (attempt + 1), 10))
        row['Error'] = '\n'.join(errors) or 'No downloadable source found'
        return row


def write_csv(path, rows, fields):
    temporary = path.with_suffix('.csv.part')
    with temporary.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def choose(prompt, options, all_option=False):
    print('\n' + prompt)
    if all_option:
        print('  0. All')
    for number, (label, _) in enumerate(options, 1):
        print(f'  {number}. {label}')
    while True:
        value = input('Choose a number (or q to quit): ').strip()
        if value.lower() == 'q':
            raise KeyboardInterrupt
        if value.isdigit():
            number = int(value)
            if all_option and number == 0:
                return options
            if 1 <= number <= len(options):
                return [options[number - 1]]
        print('Please enter one of the numbers above.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, choices=[9, 10, 11, 12], help='School year')
    parser.add_argument('--subject', help='Subject folder name, or all')
    parser.add_argument('--url', help='Download a specific THSC subject folder or paper listing')
    parser.add_argument('--exam-year', type=int, help='Optional calendar year printed in paper titles')
    parser.add_argument('--output', type=Path, default=ROOT / 'THSC Downloads')
    parser.add_argument('--list-only', action='store_true', help='Save a manifest without downloading PDFs')
    parser.add_argument('--limit', type=int, default=0, help='Download only the first N papers for a test')
    parser.add_argument('--rounds', type=int, choices=range(1, 5), default=2, help='Attempts per source (default 2)')
    args = parser.parse_args()
    if args.limit < 0:
        parser.error('--limit cannot be negative')
    if args.url:
        url = clean_url(args.url)
        if urlsplit(url).netloc != 'thsconline.github.io' or not re.match(r'^/s/yr(?:9|10|11|12)/', urlsplit(url).path):
            parser.error('--url must be a THSC year/subject page on thsconline.github.io')
        if not Path(urlsplit(url).path).suffix:
            url = url.rstrip('/') + '/'
        selections = [('Custom selection', url)]
    else:
        year = args.year or choose('School year', [(f'Year {y}', y) for y in (9, 10, 11, 12)])[0][1]
        subjects = children(f'{SITE}/s/yr{year}/', folders_only=True)
        if not subjects:
            raise RuntimeError('No subjects found. The site layout may have changed.')
        if args.subject:
            selections = subjects if args.subject.lower() == 'all' else [(n, u) for n, u in subjects if n.casefold() == args.subject.casefold()]
            if not selections:
                parser.error('Unknown subject. Available: ' + ', '.join(n for n, _ in subjects))
        else:
            selections = choose('Subject (Maths contains its individual courses)', subjects, True)
            if len(selections) == 1:
                categories = children(selections[0][1])
                if categories:
                    chosen = choose('Paper category', categories, True)
                    if chosen != categories:
                        selections = chosen
        if not args.year and not args.exam_year:
            value = input('\nExam calendar year (Enter for all years): ').strip()
            if value:
                if not re.fullmatch(r'\d{4}', value):
                    parser.error('Exam year must contain four digits')
                args.exam_year = int(value)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    all_papers, errors = {}, []
    for _, url in selections:
        papers, issues = scan(url)
        errors.extend(issues)
        for paper in papers:
            if not args.exam_year or re.search(rf'\b{args.exam_year}\b', paper.title):
                all_papers.setdefault(paper.key, paper)
    papers = list(all_papers.values())
    if args.limit:
        papers = papers[:args.limit]
    manifest = [dict(Title=p.title, Collection=p.collection, Page=p.page, URL=p.url, File=relative_path(p).as_posix()) for p in papers]
    write_csv(output / 'manifest.csv', manifest, ['Title', 'Collection', 'Page', 'URL', 'File'])
    write_csv(output / 'scan-errors.csv', errors, ['Page', 'Error'])
    print(f'\nFound {len(papers)} papers; {len(errors)} page errors. Output: {output}', flush=True)
    if args.list_only:
        return 1 if errors or not papers else 0
    if not papers:
        print('No matching papers found. See scan-errors.csv for any connection failures.')
        return 1
    downloader, rows = Downloader(args.rounds), []
    fields = ['Paper', 'Collection', 'Status', 'File', 'Source', 'Error']
    for number, paper in enumerate(papers, 1):
        print(f'[{number}/{len(papers)}] {paper.title}', flush=True)
        row = downloader.download(paper, output)
        rows.append(row)
        write_csv(output / 'download-report.csv', rows, fields)
        print('  ' + row['Status'], flush=True)
        if row['Status'] != 'Already downloaded':
            time.sleep(0.5)
    failed = sum(r['Status'] == 'Failed' for r in rows)
    print(f'\nFinished: {len(rows) - failed} saved/skipped, {failed} failed, {len(errors)} page errors.')
    print('Run the same selection again to retry failures and skip completed PDFs.')
    return 1 if failed or errors else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nStopped. Run again to resume completed downloads.')
        raise SystemExit(130)
    except Exception as error:
        print(f'\nError: {error}')
        raise SystemExit(1)
