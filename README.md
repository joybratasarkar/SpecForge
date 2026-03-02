# Reinforcement QA Agent

This project is organized into two customer-facing entry folders:

1. `backend/` - FastAPI backend and QA agent runtime
2. `fe/` - Next.js frontend (customer UI)

The existing source code remains in the current repo locations (`spec_test_pilot/`, `qa_customer_ui.py`, `customer-ui-next/`) to avoid breaking imports and scripts.  
Use the wrapper scripts inside `backend/` and `fe/` as the primary start points.

## Folder Guide

1. Backend guide: `backend/README.md`
2. Frontend guide: `fe/README.md`
3. Technical deep docs: `docs/README.md`

## Quick Start (split FE/BE)

1. Start backend:
```bash
./backend/start-backend.sh
```

2. Start frontend (new terminal):
```bash
./fe/start-frontend.sh
```

3. Open UI:
```text
http://localhost:3001
```

## One-command UI mode

If you want frontend with built-in local API routes only:

```bash
./fe/start-full-next.sh
```
