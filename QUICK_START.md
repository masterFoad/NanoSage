# NanoSage Web UI - Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Step 1: Install Dependencies (2 min)

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies
cd frontend
npm install
cd ..
```

### Step 2: Configure Environment (30 sec)

```bash
# Create .env file in root directory
echo "TAVILY_API_KEY=your_key_here" > .env

# Create frontend .env
cd frontend
echo "REACT_APP_API_URL=http://localhost:8000" > .env
echo "REACT_APP_WS_URL=ws://localhost:8000" >> .env
cd ..
```

### Step 3: Start the Application (30 sec)

**Option A: Quick Launcher (Recommended)**
```bash
python start_web_ui.py
# Then in a new terminal:
cd frontend && npm start
```

**Option B: Manual Start**
```bash
# Terminal 1: Backend
python -m uvicorn backend.api.main:app --reload

# Terminal 2: Frontend
cd frontend && npm start
```

### Step 4: Open in Browser (5 sec)

Navigate to: **http://localhost:3000**

---

## 📝 Submit Your First Query

1. **Enter a question**: "What are the benefits of machine learning?"
2. **Configure parameters**:
   - ✅ Enable Web Search
   - Documents: 5
   - Depth: 1
3. **Click "Submit Query"**
4. **Watch real-time progress**
5. **View results** in three tabs:
   - Final Answer
   - Sources
   - Search Tree
6. **Export** to Markdown, Text, or PDF

---

## 🎯 Key URLs

| Service | URL | Description |
|---------|-----|-------------|
| **Web UI** | http://localhost:3000 | Main interface |
| **API** | http://localhost:8000 | Backend API |
| **API Docs** | http://localhost:8000/docs | Interactive API docs |
| **Health** | http://localhost:8000/health | Health check |

---

## 🛠 Common Commands

### Backend
```bash
# Start backend
python -m uvicorn backend.api.main:app --reload

# Start with multiple workers (production)
uvicorn backend.api.main:app --workers 4

# Check backend health
curl http://localhost:8000/health
```

### Frontend
```bash
# Start development server
cd frontend && npm start

# Build for production
cd frontend && npm run build

# Install new dependency
cd frontend && npm install <package-name>
```

---

## 🐛 Troubleshooting

### Backend won't start
```bash
# Check if port 8000 is in use
netstat -ano | findstr :8000  # Windows
lsof -i :8000                 # Linux/Mac

# Use different port
uvicorn backend.api.main:app --port 8001
```

### Frontend can't connect
```bash
# Verify backend is running
curl http://localhost:8000/health

# Check .env file exists
cat frontend/.env

# Restart frontend
cd frontend
npm start
```

### Export fails
```bash
# Install missing dependency
pip install reportlab

# Check exports directory exists
mkdir -p exports
```

---

## 📚 Documentation

- **Full Setup Guide**: [WEB_UI_SETUP.md](WEB_UI_SETUP.md)
- **User Guide**: [WEB_UI_README.md](WEB_UI_README.md)
- **Project Structure**: [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)
- **Implementation Details**: [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)
- **Main NanoSage README**: [README.md](README.md)

---

## ⚡ Quick Tips

### Performance
- Use **SigLIP** retrieval model for best results
- Keep **max_depth = 1** for faster queries
- Enable **web_search** for comprehensive results

### Best Practices
- Start with simple queries to test setup
- Use advanced parameters only when needed
- Export results immediately after completion
- Check API docs for programmatic access

### Keyboard Shortcuts
- `Ctrl+C` in terminal: Stop server
- `F5` in browser: Refresh page
- `Ctrl+Shift+I`: Open browser DevTools

---

## 🎨 Customization

### Change Theme Colors
Edit `frontend/src/App.css`:
```css
/* Line 23-24: Primary gradient */
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
```

### Change API URL
Edit `frontend/.env`:
```
REACT_APP_API_URL=http://your-backend-url
```

### Change Default Parameters
Edit `frontend/src/components/QueryForm.tsx`:
```typescript
// Around line 11
top_k: 5,        // Change default document count
max_depth: 1,    // Change default search depth
```

---

## 📊 Status Indicators

| Color | Meaning |
|-------|---------|
| 🟡 Pending | Query submitted, waiting to start |
| 🔵 Processing | Query is being executed |
| 🟢 Completed | Query finished successfully |
| 🔴 Failed | Query encountered an error |

---

## 🔒 Security Checklist

Before deploying to production:

- [ ] Update CORS origins in `backend/api/main.py`
- [ ] Use HTTPS for backend
- [ ] Set strong API keys in `.env`
- [ ] Enable rate limiting
- [ ] Review input validation
- [ ] Use environment-specific configs

---

## 💡 Example Queries

Try these to test functionality:

1. **Quick Test**: "What is Python?"
2. **Research**: "Explain quantum computing applications"
3. **Comparison**: "Compare React and Vue frameworks"
4. **Technical**: "How does transformer architecture work?"
5. **Current Events**: "Latest developments in AI" (with web search)

---

## 🆘 Getting Help

1. **Check documentation** in the links above
2. **Review API docs**: http://localhost:8000/docs
3. **Check browser console** for frontend errors
4. **Check terminal output** for backend errors
5. **GitHub Issues**: https://github.com/masterFoad/NanoSage/issues

---

## ✅ Verification Checklist

After setup, verify everything works:

- [ ] Backend starts without errors
- [ ] Frontend opens in browser
- [ ] Can submit a simple query
- [ ] See real-time progress updates
- [ ] Results display correctly
- [ ] Can view search tree
- [ ] Can export to all formats
- [ ] Error messages appear when expected

---

**Ready to start? Run:** `python start_web_ui.py`

**Need help? See:** [WEB_UI_SETUP.md](WEB_UI_SETUP.md)
