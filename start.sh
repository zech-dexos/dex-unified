#!/bin/bash
python discord_bot.py &
uvicorn api:app --host 0.0.0.0 --port $PORT
