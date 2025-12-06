# Scraper Backend

This folder contains a Flask wrapper around the LinkedIn scraper utilities.

Quick notes on fixes made:
- Fixed package import name: the package directory is `scrapper` and `app.py` now imports from `scrapper.scraper_core`.
- Added a proper `__init__.py` in `Backend/scrapper` so the package is importable.
- Improved CLI parsing in top-level `linkedin_scraper.py` (added `get_parser()` and `-o/--output` alias).

How to run the Flask backend (from repository root):

1. Install dependencies (from project root):

```cmd
python -m pip install -r Backend\requirements.txt
```

2. Start the backend (simple dev run):

```cmd
cd Backend
python app.py
```

Note: the scraper package lives under `Backend/scrapper`. If you run scripts from the repo root, add `Backend` to `PYTHONPATH` or run Python with `-m` and the correct working directory. Example quick test:

```cmd
python -c "import sys; sys.path.insert(0, r'c:\\Users\\Mantoo\\Desktop\\Scrapper\\Backend'); import scrapper.scraper_core as m; print('create_driver' in dir(m))"
```

If you'd like, I can also:
- Rename `Backend\requirement.txt` to the conventional `requirements.txt` (done as a copy here).
- Add a small automated test harness for the CLI and package imports.
