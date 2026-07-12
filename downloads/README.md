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

```powershell
py scripts\populate_downloads.py --floor Floor_2 --source "<path to source images>"
py scripts\populate_downloads.py --floor Floor_2 --from-s3 --check
py scripts\populate_downloads.py --floor Floor_2 --from-s3
```

The first command copies an approved local source folder. The S3 commands list
under `S3_INPUT_PREFIX`, first reporting new/changed files without writing and
then downloading them. Use `--key-contains` to scope a shared prefix to the
intended floor; source files remain gitignored.
