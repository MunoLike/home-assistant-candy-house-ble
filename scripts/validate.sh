#!/usr/bin/env bash
set -euo pipefail

python scripts/version.py check
python -m pytest -q
python -m compileall -q \
  custom_components \
  firmware/components/fake_sesame \
  firmware/reference \
  firmware/tools \
  scripts \
  tests
python -m ruff check custom_components firmware scripts tests
