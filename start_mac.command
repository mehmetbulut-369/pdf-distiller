#!/bin/bash
# macOS: Finder'da çift tıklayın. İlk çalıştırmada kurulum yapar (1-2 dk).
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "İlk kurulum yapılıyor..."
  python3 -m venv .venv || { echo "Python 3 bulunamadı. https://www.python.org/downloads/ adresinden kurun."; read; exit 1; }
  ./.venv/bin/pip install --upgrade pip -q
  ./.venv/bin/pip install -r requirements.txt -q || { echo "Kurulum başarısız."; read; exit 1; }
fi
./.venv/bin/python run.py
