"""``python -m oilgas``: the guard matters on Windows, where worker processes import this module again."""

from oilgas.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
