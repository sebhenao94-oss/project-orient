# downloads/

Standard location for the source files (BMS screenshots + mechanical drawings)
the extraction pipeline runs on (Sourav W4-review #5/#6). Keeping inputs here —
rather than an arbitrary path on the machine — means the run commands in the
top-level README never need editing before a run.

Layout is per-floor:

```
downloads/
  Floor_2/
    <bms_screenshots>.png
    <mechanical_drawings>.pdf
```

The files themselves are **not committed** (building data; see `.gitignore`).
Populate the folder locally:

```bash
python scripts/populate_downloads.py --floor Floor_2 --source "<path to source images>"
```

Default source is the local screenshots folder; a future version pulls from the
`S3_INPUT_PREFIX` bucket.
