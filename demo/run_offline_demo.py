demo/run_offline_demo.py — quick offline demo of the rule-mode chat.
Drop into repo root and run with: python -m demo.run_offline_demo

The script:
1. reminds the reader to set AM_DATABASE_URL or pass --memory-db
2. runs three canned commands through Supervisor (rule mode) and prints them,
   which exercises real agent-memory for the memory worker.
