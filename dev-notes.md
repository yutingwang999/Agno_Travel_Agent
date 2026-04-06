## Step by Step note, reference later only

### 1 Concepts:

Agno, RAG, CAG, Pydantic, migrations(Alembic), SSE, Pydantic schema, PostgreSQL, docker

### 2 environment setup

python

1. anaconda install (install before)  
   conda --version  
   conda 25.5.1
2. new python 3.11.15 environment
3. anaconda navigator install:  
   fastapi uvicorn sqlalchemy psycopg alembic
   pydantic python-dotenv pytest httpx sse-starlette
4. anaconda prompt  
   conda activate python31115  
   python -m pip install agno google-generativeai  
   reference detail python environment in file
5. check conda version  
   conda info --envs

docker desktop (install before)

vscode extension

1. vscode install (install before)
2. install extension:  
   Codex – OpenAI's coding agent (install before)  
   GitHub Copilot Chat  
   Claude code for VS code

vscode python  
Python: Select Interpreter  
check python:  
import sys  
print(sys.executable)

agent/AI/chatbox  
gemini api (already have)  
chatgpt plus (already have)  
claude api

git(install before)

vscode setting for quick verify:  
ctrl+shift+p - python:select interpreter - choose env  
add .vscode/settings.json  
{
"python.defaultInterpreterPath": "C:/Users/username/.conda/envs/python31115/python.exe",
"python.terminal.activateEnvironment": true
}  
open terminal, run `conda init powershell` and restart vscode -- quit eventually  
stay with python path

### 3 Work steps in docs

Design.md  
logic-diagram.png  
CLAUDE.md

### 4 coding plan in docs

generate a plan with claude code:

```
give a feature branch plan + merge checklist in docs/git-workflow.md, according to docs/DESIGN.md and  docs/CLAUDE.md
The purpose of this workflow is to:
- keep `main` stable
- Each major unit of work must be implemented in its own feature branch.
- make development history easy to review
- support incremental implementation
- align with the project requirement that the `main` branch should always be working

List Definition of "Main Must Stay Runnable", Scope of each branch, Merge checklist of each branch, why in this order
```

Claude return

```
docs/git-workflow.md is written. Here's what it contains:

Section 1 — "Main Must Stay Runnable" — 8 concrete, testable criteria specific to this stack (Docker, Alembic, uvicorn, pytest, /generate endpoint, imports, env vars, stubs).

Section 2 — 13 Feature Branches in dependency order:

| Number | Branch                         | Key reason for position |
|--------|--------------------------------|--------------------------|
| 1      | feat/project-scaffold          | nothing runs without an environment |
| 2      | feat/db-schema                 | tables must exist before anything reads/writes them |
| 3      | feat/db-seed                   | CAG/RAG steps need query targets |
| 4      | feat/workflow-skeleton         | fixes step interface before any step is written |
| 5–10   | feat/intake → feat/validate-output | steps in workflow order; each reads from the one before |
| 11     | feat/fastapi-service           | wraps a complete workflow |
| 12     | feat/observability             | added after steps are correct, so DB write failures don't mask logic bugs |
| 13     | feat/testing                   | golden + e2e tests need the full pipeline |

Section 4 — Why This Order — plain-language explanation of the dependency chain.
```

### 4 feature/project-scaffold

### 5 feat/db-schema
