# THSC Extractor — choose year and subject

First extract the entire ZIP into a writable folder on your computer.
Then double-click **Start THSC Extractor.cmd** (Windows). Choose a school year (9–12), a subject,
and a category, or choose **0. All**. Maths courses share the Maths subject folder;
the next menu lets you choose the individual course/category. You can optionally
filter by exam calendar year; leave it blank to include every listed year.

Each coworker needs Python 3.10 or newer installed and available as the python command.
No extra packages are needed. Keep the window open while downloads run.

Files save under **THSC Downloads / yr12 / Physics / trialpapers**, for example.
The small ID at the end of each filename prevents similarly named papers from
overwriting each other. Papers and separately listed solutions/marking guidelines
are included. A subject-wide run follows all linked listing pages within that
subject, including HSC, trials, and assessments where available.

The extractor tries the site's current API, published per-paper mirrors where
available, and alternate Google download servers discovered from the live viewer.
After exhausting the sources it retries the sequence once. Listing requests also
fall back to the site's Cloudflare mirror. It validates PDF header/end markers,
writes completed files atomically, and skips valid completed files on subsequent
runs. Stop with **Ctrl+C**; rerun the same selection to resume. Downloads are
sequential with a short delay, and a request times out after 45 seconds. An
unavailable paper can take several minutes while all alternate servers are tried.

Reports in the output folder describe the latest run:

- `manifest.csv`: every discovered paper in the selection, with source page and filename.
- `download-report.csv`: saved/skipped/failed files, successful source, and failure details.
- `scan-errors.csv`: listing pages that could not be read. These mean discovery is incomplete.

No extractor can retrieve a paper if all published sources are unavailable.
Failures are reported and retried on the next run. This tool downloads linked PDFs;
external resource websites and other file formats are not recursively crawled.

Command-line examples (run from this folder):

```powershell
# All Year 12 Physics categories and exam years
python thsc_extractor.py --year 12 --subject Physics

# Just Physics trials
python thsc_extractor.py --url https://thsconline.github.io/s/yr12/Physics/trialpapers.html

# Chemistry, Year 11, papers dated 2023
python thsc_extractor.py --year 11 --subject Chemistry --exam-year 2023

# Every subject in Year 12: list first without downloading
python thsc_extractor.py --year 12 --subject all --list-only

# Download every listed paper across all Year 12 subjects
python thsc_extractor.py --year 12 --subject all

# One-paper test, or choose an output directory
python thsc_extractor.py --year 12 --subject Physics --limit 1 --output "My Papers"

# Run the automated checks
python -m unittest -v test_thsc_extractor.py
```

