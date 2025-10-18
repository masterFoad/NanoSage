# NanoSage Web Interface

A modern, responsive web-based user interface for NanoSage's advanced recursive search and report generation system.

## Features

### Core Functionality (All Requirements Implemented)

✅ **Query Submission (UC-1, FR-1)**
- Text input field for entering queries
- Submit button to trigger processing
- Real-time validation of query text

✅ **Query Parameter Customization (UC-2, FR-2, FR-3)**
- Enable/disable web search
- Configure number of documents (1-20)
- Set search depth (1-3)
- Advanced parameters: retrieval model, LLM provider, personality, and more
- Parameter validation with clear error messages

✅ **Progress Feedback (UC-1, FR-4, NFR-1, NFR-8)**
- Visual loading spinner appears within 1 second
- Real-time progress bar with percentage
- WebSocket-based live updates
- Activity log with timestamped events
- Current step and message display

✅ **Error Handling (UC-1, FR-5, NFR-9, NFR-13)**
- Clear error messages for all failure scenarios:
  - "Unable to fetch web results" for web search failures
  - "Unable to access local sources" for local search failures
  - "Enter a valid query" for empty queries
- Error messages display within 1 second of detection
- System remains responsive after errors
- No page reloads required

✅ **Results Display (UC-3, FR-6, FR-7, FR-9)**
- Final aggregated result prominently displayed
- Source list with snippets and links
- Copy-to-clipboard functionality
- Clean, readable layout

✅ **Search Tree Visualization (UC-3, FR-8)**
- Interactive, expandable tree structure
- Relevance scores for each node
- Node metrics (web results, documents, processing time)
- "Search tree unavailable" message when not generated

✅ **Export Functionality (UC-4, FR-10, FR-11, FR-12)**
- Export to Markdown, Text, or PDF formats
- Includes query text, results, and sources
- Success confirmation message
- Automatic file download

✅ **Web User Interface (FR-14, FR-15, FR-16)**
- Query input area with parameter controls
- Export format selector with export button
- Clean, professional design
- Intuitive navigation

### Non-Functional Requirements

✅ **Performance (NFR-1 - NFR-4)**
- Loading indicator appears in < 1 second
- Optimized for local and web search scenarios
- Concurrent request handling via async/await
- No performance degradation during operation

✅ **Compatibility (NFR-5)**
- Works on Chrome, Firefox, Edge (latest versions)
- Tested on modern browsers

✅ **Usability (NFR-6 - NFR-12)**
- All features accessible from visible UI elements
- Plain language messages (no technical jargon)
- Visual feedback for long operations
- Responsive design for desktop, tablet, and mobile
- Consistent layout across browsers
- Mobile-friendly interface

✅ **Reliability (NFR-13)**
- Error recovery without page reload
- Graceful degradation
- Persistent WebSocket connections with auto-reconnect

✅ **Security (NFR-14)**
- Input validation on both client and server
- Sanitization of user input
- Protection against malformed requests

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        User Browser                         │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │           React Frontend (Port 3000)                │  │
│  │                                                     │  │
│  │  • Query Form with Parameter Controls              │  │
│  │  • Real-time Progress Tracker                      │  │
│  │  • Results Display with Tabs                       │  │
│  │  • Interactive Search Tree Visualization           │  │
│  │  • Export Panel (MD/Text/PDF)                      │  │
│  └─────────────────────────────────────────────────────┘  │
│              │                            │                 │
│              │ HTTP REST                  │ WebSocket       │
│              ▼                            ▼                 │
└─────────────────────────────────────────────────────────────┘
               │                            │
               │                            │
┌──────────────▼────────────────────────────▼─────────────────┐
│                  FastAPI Backend (Port 8000)                │
│                                                             │
│  ┌─────────────────────┐     ┌──────────────────────────┐  │
│  │   REST API Routes   │     │   WebSocket Manager      │  │
│  │                     │     │                          │  │
│  │  • POST /submit     │     │  • Real-time updates     │  │
│  │  • GET /query/{id}  │     │  • Progress tracking     │  │
│  │  • POST /export     │     │  • Connection mgmt       │  │
│  └─────────────────────┘     └──────────────────────────┘  │
│              │                                              │
│              ▼                                              │
│  ┌───────────────────────────────────────────────────────┐ │
│  │              Services Layer                           │ │
│  │                                                       │ │
│  │  ┌─────────────────┐      ┌────────────────────┐    │ │
│  │  │  Query Service  │      │  Export Service    │    │ │
│  │  │                 │      │                    │    │ │
│  │  │ • Validation    │      │ • MD Export        │    │ │
│  │  │ • Execution     │      │ • Text Export      │    │ │
│  │  │ • Status Mgmt   │      │ • PDF Export       │    │ │
│  │  └─────────────────┘      └────────────────────┘    │ │
│  └───────────────────────────────────────────────────────┘ │
│              │                                              │
│              ▼                                              │
│  ┌───────────────────────────────────────────────────────┐ │
│  │           NanoSage Core (SearchSession)               │ │
│  │                                                       │ │
│  │  • Query Enhancement                                  │ │
│  │  • Recursive Web Search                               │ │
│  │  • Knowledge Base Management                          │ │
│  │  • RAG-based Report Generation                        │ │
│  │  • TOC Tree Building                                  │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Technology Stack

### Backend
- **FastAPI**: Modern, fast web framework
- **Uvicorn**: ASGI server
- **Pydantic v2**: Data validation
- **WebSockets**: Real-time communication
- **ReportLab**: PDF generation

### Frontend
- **React 18**: UI library
- **TypeScript**: Type-safe JavaScript
- **Axios**: HTTP client
- **React Markdown**: Markdown rendering
- **CSS3**: Styling with gradients and animations

## Quick Start

### 1. Install Dependencies

```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

### 2. Start the Application

**Option A: Use the launcher script (Recommended)**
```bash
python start_web_ui.py
```

**Option B: Manual start**

Terminal 1 (Backend):
```bash
python -m uvicorn backend.api.main:app --reload
```

Terminal 2 (Frontend):
```bash
cd frontend
npm start
```

### 3. Access the Interface

Open your browser to: **http://localhost:3000**

## User Guide

### Submitting a Query

1. **Enter your query** in the text area
2. **Configure basic parameters**:
   - Toggle "Enable Web Search"
   - Set "Number of Documents" (recommended: 5)
   - Set "Search Depth" (recommended: 1)
3. **Optionally configure advanced parameters**:
   - Click "▶ Advanced Parameters"
   - Choose retrieval model (SigLIP recommended)
   - Select LLM provider
   - Set personality, corpus directory, etc.
4. **Click "Submit Query"**

### Monitoring Progress

Watch the real-time updates:
- **Progress bar**: Shows completion percentage
- **Current message**: What NanoSage is doing now
- **Activity log**: Complete timeline of events

### Viewing Results

Once complete, explore three tabs:

**1. Final Answer**
- The aggregated report
- Copy button for easy sharing
- Export panel at the bottom

**2. Sources**
- Web sources with URLs
- Local sources from your corpus
- Relevance scores for each

**3. Search Tree**
- Visual exploration path
- Click nodes to expand/collapse
- See metrics for each branch

### Exporting Results

1. Go to the "Final Answer" tab
2. Scroll to the "Export Results" section
3. Choose format: Markdown, Plain Text, or PDF
4. Click "Export"
5. File downloads automatically

## API Documentation

The backend provides a RESTful API with the following endpoints:

### Endpoints

**Submit Query**
```http
POST /api/query/submit
Content-Type: application/json

{
  "parameters": {
    "query": "your question",
    "web_search": true,
    "retrieval_model": "siglip",
    "top_k": 5,
    "max_depth": 1
  }
}
```

**Get Query Status**
```http
GET /api/query/{query_id}
```

**List All Queries**
```http
GET /api/queries?limit=50
```

**Export Query**
```http
POST /api/query/export
Content-Type: application/json

{
  "query_id": "uuid-here",
  "format": "markdown"
}
```

**WebSocket Connection**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/{query_id}');
```

Full interactive documentation: **http://localhost:8000/docs**

## Customization

### Changing Colors/Styling

Edit `frontend/src/App.css`:
```css
/* Primary gradient */
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

/* Accent colors */
--primary: #667eea;
--success: #27ae60;
--error: #e74c3c;
```

### Adding New Parameters

1. Update `backend/api/models.py`:
```python
class QueryParameters(BaseModel):
    your_new_param: str = Field(default="value")
```

2. Update `frontend/src/types/index.ts`:
```typescript
export interface QueryParameters {
  your_new_param: string;
}
```

3. Add form field in `frontend/src/components/QueryForm.tsx`

### Custom Export Formats

Extend `backend/services/export_service.py`:
```python
def _export_custom(self, result: QueryResult, file_path: str):
    # Your custom export logic
    pass
```

## Deployment

### Production Backend

```bash
# Install production server
pip install gunicorn

# Run with multiple workers
gunicorn backend.api.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

### Production Frontend

```bash
cd frontend
npm run build

# Serve the build directory with any static server
# Or use services like Vercel, Netlify, etc.
```

### Environment Variables

**Backend** (.env in root):
```
TAVILY_API_KEY=your_key
```

**Frontend** (frontend/.env):
```
REACT_APP_API_URL=https://your-backend-domain.com
REACT_APP_WS_URL=wss://your-backend-domain.com
```

## Troubleshooting

### "Port 8000 already in use"
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <pid> /F

# Linux/Mac
lsof -i :8000
kill -9 <pid>
```

### Frontend can't connect to backend
- Check backend is running: http://localhost:8000/health
- Verify `.env` file in frontend directory
- Check browser console for CORS errors

### Export fails
- Ensure reportlab is installed: `pip install reportlab`
- Check exports/ directory is writable
- View browser console for error details

### WebSocket disconnects
- Normal after query completes
- Check browser console for connection errors
- Verify backend WebSocket route is accessible

## Contributing

Contributions are welcome! Areas for improvement:

- [ ] User authentication
- [ ] Query history persistence
- [ ] Saved searches
- [ ] Share results via URL
- [ ] Dark mode
- [ ] Mobile app
- [ ] Advanced visualizations
- [ ] Multi-language support

## License

Same as NanoSage main project (see LICENSE file)

## Support

- GitHub Issues: https://github.com/masterFoad/NanoSage/issues
- Documentation: [WEB_UI_SETUP.md](WEB_UI_SETUP.md)
- API Docs: http://localhost:8000/docs

---

**Built with NanoSage** | Powered by FastAPI + React
