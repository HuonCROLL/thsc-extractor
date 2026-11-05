import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import thsc_extractor as t

PDF = b'%PDF-1.4\nexample test payload\n%%EOF\n'
PAGE = t.SITE + '/s/yr12/Physics/trialpapers.html'


class ExtractorTests(unittest.TestCase):
    def test_dynamic_and_direct_links(self):
        links = t.Links('''<a onclick="pdf(this, 6528)" href="#v">School 2025 <b>w. sol</b></a>
            <a href="paper.pdf">Extra paper</a><a href="/s/v/6520/2025%20HSC">HSC</a>''').links
        papers = t.papers_on(PAGE, links)
        self.assertEqual(len(papers), 3)
        self.assertEqual(papers[0].title, 'School 2025 w. sol')
        self.assertEqual(papers[2].collection, '6520')

    def test_fallback_rejects_html_then_saves_and_resumes(self):
        paper = t.Paper('School 2025', '6528', '', PAGE)
        d = t.Downloader(1, log=lambda _: None)
        d.indexes['6528'] = {}
        d.workers = ['AKfy_one', 'AKfy_two']
        with tempfile.TemporaryDirectory(dir=t.ROOT) as directory:
            output = Path(directory)
            with patch.object(d, 'primary', side_effect=TimeoutError('offline')), patch.object(t, 'fetch', side_effect=[b'<html>error</html>', json.dumps({'data': base64.b64encode(PDF).decode()}).encode()]) as fetch:
                row = d.download(paper, output)
                self.assertEqual(row['Status'], 'Downloaded')
                self.assertEqual(fetch.call_count, 2)
                self.assertIn('AKfy_two', row['Source'])
            with patch.object(t, 'fetch', side_effect=AssertionError('Resume must not fetch')):
                self.assertEqual(d.download(paper, output)['Status'], 'Already downloaded')
            self.assertFalse(list(output.rglob('*.part')))

    def test_fragments_join_in_order(self):
        data = gzip.compress(PDF)
        with patch.object(t, 'fetch', side_effect=[b'{"fragmentCount":2}', data[:8], data[8:]]):
            self.assertEqual(t.Downloader().primary(t.Paper('Test', '1', '', PAGE)), PDF)

    def test_failed_download_has_no_final_pdf(self):
        d = t.Downloader(1, log=lambda _: None)
        paper = t.Paper('Test', '', 'https://example.org/p.pdf', PAGE)
        with tempfile.TemporaryDirectory(dir=t.ROOT) as directory, patch.object(t, 'fetch', return_value=b'%PDF-truncated'):
            row = d.download(paper, Path(directory))
            self.assertEqual(row['Status'], 'Failed')
            self.assertIn('complete PDF', row['Error'])
            self.assertFalse(list(Path(directory).rglob('*.pdf')))

    def test_page_failure_reported_and_scan_stays_in_subject(self):
        subject = t.SITE + '/s/yr12/Physics/'
        html = '<a href="trialpapers.html">Trials</a><a href="../Chemistry/">Other</a>'
        with patch.object(t, 'page_links', side_effect=[t.Links(html).links, OSError('offline')]) as pages:
            papers, errors = t.scan(subject, log=lambda _: None)
            self.assertEqual(papers, [])
            self.assertEqual(len(errors), 1)
            self.assertEqual(pages.call_count, 2)

    def test_paths_are_safe_and_distinct(self):
        a = t.Paper('../CON: test', '1', '', PAGE)
        b = t.Paper('../CON? test', '1', '', PAGE)
        self.assertNotEqual(t.relative_path(a), t.relative_path(b))
        self.assertNotIn('..', t.relative_path(a).parts)
        self.assertEqual(t.safe_name('CON'), '_CON')

    def test_embed_url(self):
        self.assertEqual(t.direct_url('/s/em/papers/Example'), t.SITE + '/papers/Example.pdf')


if __name__ == '__main__':
    unittest.main()
