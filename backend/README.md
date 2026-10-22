# jobsoo backend

FastAPI + SQLAlchemy 2.x + Alembic backend for the Job Application Intelligence Platform.

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # then fill in real values
alembic upgrade head
uvicorn app.main:app --reload
```

## Commands

```bash
ruff check .          # lint
ruff format --check . # formatting check
mypy app              # type check
pytest                # tests
```
