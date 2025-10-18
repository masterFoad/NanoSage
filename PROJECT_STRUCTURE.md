# NanoSage Project Structure

This document provides an overview of the complete NanoSage project structure after adding the web UI.

## Directory Tree

```
NanoSage/
│
├── 📁 backend/                          # FastAPI Backend
│   ├── __init__.py
│   ├── 📁 api/                          # API Layer
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI application & routes
│   │   ├── models.py                    # Pydantic data models
│   │   └── websocket.py                 # WebSocket connection manager
│   ├── 📁 services/                     # Business Logic
│   │   ├── __init__.py
│   │   ├── query_service.py             # Query execution service
│   │   └── export_service.py            # Export functionality (MD/Text/PDF)
│   └── 📁 utils/                        # Utilities
│       ├── __init__.py
│       └── validators.py                # Input validation & sanitization
│
├── 📁 frontend/                         # React Frontend
│   ├── 📁 public/                       # Static files
│   │   └── index.html                   # HTML template
│   ├── 📁 src/                          # Source code
│   │   ├── 📁 components/               # React components
│   │   │   ├── QueryForm.tsx            # Query submission form
│   │   │   ├── ProgressTracker.tsx      # Real-time progress display
│   │   │   ├── ResultsDisplay.tsx       # Results with tabs
│   │   │   ├── SearchTree.tsx           # Interactive tree visualization
│   │   │   └── ExportPanel.tsx          # Export controls
│   │   ├── 📁 services/                 # API Client
│   │   │   └── api.ts                   # Axios-based API wrapper
│   │   ├── 📁 types/                    # TypeScript definitions
│   │   │   └── index.ts                 # All type definitions
│   │   ├── App.tsx                      # Main application component
│   │   ├── App.css                      # Application styles
│   │   ├── index.tsx                    # React entry point
│   │   └── index.css                    # Global styles
│   ├── .env.example                     # Environment variables template
│   ├── package.json                     # NPM dependencies
│   └── tsconfig.json                    # TypeScript configuration
│
├── 📁 exports/                          # Generated export files (gitignored)
│
├── 📁 results/                          # Query results (gitignored)
│
├── Core Python Modules:
├── __init__.py                          # Package initialization
├── aggregator.py                        # Results aggregation
├── knowledge_base.py                    # Document embedding & retrieval
├── llm_interface.py                     # LLM provider abstraction
├── main.py                              # CLI entry point
├── search_session.py                    # Main search orchestration
├── web_crawler.py                       # Web content fetching
└── web_search.py                        # Search API integration
│
├── Configuration:
├── config.yaml                          # NanoSage configuration
├── .env                                 # API keys (gitignored)
├── env.example                          # Environment template
├── requirements.txt                     # Python dependencies
└── .gitignore                           # Git ignore rules
│
├── Documentation:
├── README.md                            # Main project documentation
├── WEB_UI_README.md                     # Web UI documentation
├── WEB_UI_SETUP.md                      # Setup & installation guide
├── PROJECT_STRUCTURE.md                 # This file
├── example_report.md                    # Example output
└── LICENSE                              # License file
│
└── Scripts:
    └── start_web_ui.py                  # Quick launcher script
```

## Component Responsibilities

### Backend Components

#### API Layer
- **main.py**: FastAPI application, routes, middleware, exception handlers
- **models.py**: Pydantic models for request/response validation
- **websocket.py**: WebSocket connection management for real-time updates

#### Services
- **query_service.py**:
  - Query submission and execution
  - Status tracking
  - Integration with SearchSession
  - Progress callbacks

- **export_service.py**:
  - Markdown export
  - Plain text export
  - PDF generation (via reportlab)

#### Utils
- **validators.py**: Input validation and sanitization

### Frontend Components

#### Components
- **QueryForm.tsx**: User input with parameter controls
- **ProgressTracker.tsx**: Real-time progress visualization
- **ResultsDisplay.tsx**: Tabbed results interface
- **SearchTree.tsx**: Recursive tree visualization
- **ExportPanel.tsx**: Export format selection

#### Services
- **api.ts**: HTTP and WebSocket communication

#### Types
- **index.ts**: TypeScript type definitions

### Core NanoSage Modules

- **search_session.py**: Main orchestrator
- **knowledge_base.py**: Vector storage and retrieval
- **llm_interface.py**: Multi-provider LLM abstraction
- **web_crawler.py**: Web content extraction
- **aggregator.py**: Results compilation

## Data Flow

### Query Submission Flow

```
1. User submits query via QueryForm
   ↓
2. Frontend sends POST to /api/query/submit
   ↓
3. Backend validates parameters (validators.py)
   ↓
4. QueryService creates SearchSession
   ↓
5. SearchSession starts processing
   ↓
6. Progress updates sent via WebSocket
   ↓
7. Frontend updates ProgressTracker
   ↓
8. SearchSession completes
   ↓
9. Results stored in QueryService
   ↓
10. Frontend polls /api/query/{id}
   ↓
11. ResultsDisplay shows final answer
```

### Export Flow

```
1. User selects format in ExportPanel
   ↓
2. Frontend sends POST to /api/query/export
   ↓
3. ExportService retrieves query result
   ↓
4. ExportService generates file (MD/Text/PDF)
   ↓
5. File saved to exports/ directory
   ↓
6. Backend returns download URL
   ↓
7. Frontend triggers automatic download
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/query/submit` | Submit new query |
| GET | `/api/query/{query_id}` | Get query status/results |
| GET | `/api/queries` | List all queries |
| POST | `/api/query/export` | Export query results |
| WS | `/ws/{query_id}` | WebSocket for progress |
| GET | `/health` | Health check |
| GET | `/docs` | API documentation |

## Environment Variables

### Backend (.env in root)
```bash
TAVILY_API_KEY=your_tavily_api_key
```

### Frontend (frontend/.env)
```bash
REACT_APP_API_URL=http://localhost:8000
REACT_APP_WS_URL=ws://localhost:8000
```

## Dependencies

### Backend (Python)
- FastAPI: Web framework
- Uvicorn: ASGI server
- Pydantic: Data validation
- WebSockets: Real-time communication
- ReportLab: PDF generation
- (Plus all existing NanoSage dependencies)

### Frontend (Node.js)
- React: UI framework
- TypeScript: Type safety
- Axios: HTTP client
- React Markdown: Markdown rendering

## Build & Run

### Development
```bash
# Terminal 1: Backend
python -m uvicorn backend.api.main:app --reload

# Terminal 2: Frontend
cd frontend && npm start
```

### Production
```bash
# Backend
gunicorn backend.api.main:app -w 4 -k uvicorn.workers.UvicornWorker

# Frontend
cd frontend && npm run build
# Serve frontend/build/ with any static server
```

## Key Features Implemented

✅ All functional requirements (FR-1 through FR-16)
✅ All non-functional requirements (NFR-1 through NFR-14)
✅ All use cases (UC-1 through UC-4)
✅ All user stories with acceptance criteria
✅ Complete error handling
✅ Real-time progress tracking
✅ Responsive design
✅ Export functionality
✅ Input validation
✅ Security measures

## Next Steps for Enhancement

- [ ] User authentication system
- [ ] Query history database
- [ ] Results caching
- [ ] Advanced analytics
- [ ] Collaborative features
- [ ] Mobile app
- [ ] API rate limiting
- [ ] Monitoring & logging

---

For detailed setup instructions, see [WEB_UI_SETUP.md](WEB_UI_SETUP.md)

For usage guide, see [WEB_UI_README.md](WEB_UI_README.md)
