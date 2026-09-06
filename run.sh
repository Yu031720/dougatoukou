#!/bin/bash
# 起動スクリプト: ./run.sh  で立ち上がります
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
else
  . .venv/bin/activate
fi
python app.py
