# AUTOSAR High-Level Design (HLD) Document Analysis Assistant

An enterprise-grade, safety-intelligence and architectural analysis platform designed to ingest, analyze, extract, and audit AUTOSAR Classic and Adaptive High-Level Design (HLD) software specifications.

The platform combines **evidence-grounded Retrieval-Augmented Generation (RAG)** with **structured architectural entity extraction**, **revision delta comparison**, **dependency mapping**, and a **governance audit trail with human-in-the-loop specialist sign-off**.

---

## 🌟 Key Capabilities

### 1. Grounded Architecture Q&A (RAG with Traceable Citations)
- Semantic search across isolated, program-specific vector collections (ChromaDB + Sentence Transformers).
- Precise citations with Document Name, Page Number, and Section for every architectural statement.
- Transparent retrieval proximity indicator with explicit uncalibrated heuristic disclosures for automotive compliance.
- OCR fallback for scanned diagrams and legacy image-based specification sheets.

### 2. Structured Architecture Extraction & Knowledge Base
- **BSW Modules & MCAL Drivers**: Formal detection and classification across Classic/Adaptive layers (Services, RTE, ECU Abstraction, MCAL, CDD).
- **Application Software Components (SWCs)**: Dynamic recognition of custom functional components.
- **Port Declarations**: Industry-standard port syntax recognition (`PPort_*`, `RPort_*`, `PRPort_*`, `P_*`, `R_*`, `Pp*`, `Rp*`, ARXML tags).
- **Assembly Connectors & Dependency Maps**: Explicit interaction detection (`provides services to`, `routes to`, `calls`) and sentence-level co-occurrence analysis.
- **Deduplicated Multi-Document Accumulation**: Re-uploading document revisions replaces stale entities without duplication, while multi-document programs accumulate cross-document dependencies cleanly.
- **Noise Blocklist with Plural Stemming**: Filters out generic spec vocabulary (`Driver`, `External`, `Generic`, `Services`) to maintain high precision.

### 3. Revision Comparison & Inconsistency Analysis
- Automated delta diffing between specification revisions.
- Identifies added/removed SWCs, modified interface contracts, and orphaned dependencies.
- Generates actionable engineering alerts (e.g., breaking interface mutations, isolated components).

### 4. Structured Export Formats
- **Complete Architecture Dossier (JSON)**: Full inventory of components, ports, interfaces, dependencies, and inconsistency matrix.
- **Component Inventory (CSV)**: Spreadsheet-ready format for systems engineering and safety tracking.
- **Formal Engineering Review Report (Markdown)**: Executive summary, component tables, port tables, dependencies, and governance sign-off blocks.

### 5. Engineering Governance & Audit Trail
- Immutable audit log of all uploads, queries, confidence indicators, and human review dispositions.
- Human-in-the-Loop disposition workflow (`ACCEPTED`, `MODIFIED`, `REJECTED`) with rationale capture for compliance dossiers (ASPICE / ISO 26262).

---

## 🛡️ Security Architecture

- **Role-Based Access Control (RBAC)**: Fine-grained roles (`admin`, `architect`, `engineer`) enforcing write/upload restrictions.
- **Secure by Default**: `SEED_DEMO_DATA` defaults to `false`. No static or predictable backdoor bearer tokens are seeded.
- **Ephemeral Session Tokens**: Cryptographically secure bearer tokens (`secrets.token_urlsafe(32)`) with automatic expiration (`SESSION_TOKEN_EXPIRE_HOURS`, 12h default).
- **Server-Side Token Revocation**: Dedicated `/api/v1/auth/logout` endpoint invalidates tokens on the server side.
- **Path Traversal Protection**: Upload filenames are strictly sanitized against directory traversal attacks.
- **Isolated Program Workspaces**: Enforces strict boundaries between ECU program collections.

---

## 📁 Repository Structure

```
├── docker-compose.yml                            # Multi-container orchestration
├── .gitignore
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt                          # Production Python dependencies
│   ├── test_features.py                          # Comprehensive feature & regression tests
│   ├── test_security.py                          # RBAC, auth, and security audit tests
│   └── app/
│       ├── main.py                               # FastAPI application entrypoint
│       ├── config.py                             # Central configuration & environment settings
│       ├── database.py                           # SQLite schema, migrations, and ORM models
│       ├── auth.py                               # PBKDF2 hashing, bearer tokens, RBAC dependencies
│       ├── models.py                             # Pydantic schemas and API contracts
│       ├── api/
│       │   └── endpoints.py                      # REST endpoints (auth, upload, query, diff, export)
│       └── services/
│           ├── ingestion.py                      # PDF parsing, OCR fallback, ChromaDB chunking
│           ├── extractor.py                      # Rule-based architectural entity extraction
│           ├── comparator.py                     # Revision diff engine & inconsistency checks
│           ├── exporter.py                       # JSON, CSV, and Markdown report generators
│           └── rag.py                            # Ollama LLM integration & grounded retrieval
└── frontend/
    ├── Dockerfile
    ├── requirements.txt                          # Streamlit frontend dependencies
    └── app.py                                    # Interactive Streamlit dashboard
```

---

## 🚀 Quickstart Guide

### Option 1: Docker Compose (Recommended)

1. Ensure [Docker](https://www.docker.com/) and [Ollama](https://ollama.ai/) are running on your host machine.
2. Pull your desired LLM model (default is `llama3`):
   ```bash
   ollama pull llama3
   ```
3. Launch the platform:
   ```bash
   docker-compose up --build
   ```
4. Access the applications:
   - **Streamlit Frontend Dashboard**: [http://localhost:8501](http://localhost:8501)
   - **FastAPI OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

### Option 2: Local Python Virtual Environment

#### 1. Backend Setup
```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

To run the backend development server:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 2. Frontend Setup
```bash
cd frontend
pip install -r requirements.txt
streamlit run app.py --server.port 8501
```

---

## 🧪 Automated Test Suites

The codebase includes two independent test suites verifying all architectural, functional, and security requirements:

### Feature & Architecture Validation Suite
Tests document upload, OCR fallback, inventory deduplication across revisions, multi-document accumulation, false-positive filtering, real project HLD port extraction, revision diffing, structured exports, and governance logs:
```bash
python backend/test_features.py
```

### Security & RBAC Audit Suite
Tests health checks, unauthenticated access blocking, PBKDF2 password verification, role-based upload barriers, path traversal resilience, project isolation, backdoor token rejection, server-side session revocation, and token expiration:
```bash
python backend/test_security.py
```

---

## ⚙️ Key Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `LLM_PROVIDER` | `ollama` | LLM backend (`ollama`, extensible to any OpenAI-compatible API) |
| `OLLAMA_MODEL` | `llama3` | Active model (`llama3`, `mistral`, `qwen`, `deepseek`) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama service endpoint |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-Transformers embedding model |
| `SEED_DEMO_DATA` | `false` | Gate for seeding demo accounts (disable in production) |
| `SESSION_TOKEN_EXPIRE_HOURS` | `12` | Lifetime of bearer tokens before re-authentication |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:8501...` | Comma-separated allowed frontend origins |
| `MAX_FILE_SIZE` | `52428800` (50MB) | Upload file size ceiling |

---

## 📄 License & Governance Notice

AI-generated architecture extraction and analysis must be verified by an authorized system architect before being utilized for ISO 26262 compliance, vehicle safety sign-off, or production code generation.
