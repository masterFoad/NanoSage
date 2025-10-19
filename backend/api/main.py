# backend/api/main.py

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import uvicorn
from datetime import datetime

from backend.api.models import (
    QuerySubmitRequest,
    QuerySubmitResponse,
    QueryResult,
    ExportRequest,
    ExportResponse,
    ErrorResponse,
    ProgressUpdate,
    FileUploadResponse
)
from backend.services.query_service import query_service
from backend.services.export_service import export_service
from backend.services.history_service import history_service
from backend.services.file_upload_service import file_upload_service
from backend.api.websocket import manager
from backend.utils.validators import validate_query_parameters, ValidationError


# Create FastAPI app
app = FastAPI(
    title="NanoSage API",
    description="Advanced Recursive Search & Report Generation API",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create exports and uploads directories
os.makedirs("exports", exist_ok=True)
os.makedirs("uploads", exist_ok=True)

# Mount static files for exports
app.mount("/exports", StaticFiles(directory="exports"), name="exports")

# Sync history from existing results folder on startup
history_service.sync_from_results_folder()


@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "message": "NanoSage API",
        "version": "1.0.0",
        "endpoints": {
            "submit_query": "/api/query/submit",
            "get_query": "/api/query/{query_id}",
            "list_queries": "/api/queries",
            "export": "/api/query/export",
            "upload_file": "/api/files/upload",
            "websocket": "/ws/{query_id}"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/files/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a file to be used as corpus for RAG

    Supported file types:
    - PDF (.pdf)
    - Text (.txt)
    - Images (.png, .jpg, .jpeg)

    Returns file metadata including file_id to be used in query parameters.
    """
    try:
        metadata = await file_upload_service.upload_file(file)

        return FileUploadResponse(
            file_id=metadata['file_id'],
            filename=metadata['original_filename'],
            file_type=metadata['file_type'],
            file_size=metadata['file_size'],
            message=f"File '{metadata['original_filename']}' uploaded successfully"
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")


@app.post("/api/query/submit", response_model=QuerySubmitResponse)
async def submit_query(request: QuerySubmitRequest):
    """
    Submit a new query for processing

    This endpoint validates the query parameters and starts processing
    in the background. Use the returned query_id to track progress via
    WebSocket or polling the /api/query/{query_id} endpoint.
    """
    try:
        # Validate parameters
        validate_query_parameters(request.parameters)

        # Create progress callback
        async def progress_callback(update: dict):
            await manager.send_progress_update(update['query_id'], update)

        # Submit query
        query_id = await query_service.submit_query(
            parameters=request.parameters,
            progress_callback=progress_callback
        )

        return QuerySubmitResponse(
            query_id=query_id,
            status="accepted",
            message="Query submitted successfully. Use the query_id to track progress."
        )

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/query/{query_id}", response_model=QueryResult)
async def get_query(query_id: str):
    """
    Get the status and results of a query

    Returns the current status of the query, including results if completed.
    """
    result = query_service.get_query_status(query_id)

    if result is None:
        raise HTTPException(status_code=404, detail=f"Query not found: {query_id}")

    return result


@app.get("/api/queries", response_model=list[QueryResult])
async def list_queries(limit: int = 50):
    """
    List all queries

    Returns a list of all queries (both active and completed),
    sorted by creation time (most recent first).
    """
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")

    return query_service.list_queries(limit=limit)


@app.post("/api/query/export", response_model=ExportResponse)
async def export_query(request: ExportRequest):
    """
    Export query results to a file

    Exports the query results to the specified format (markdown, text, or pdf).
    Returns a download URL for the exported file.
    """
    # Get query result
    result = query_service.get_query_status(request.query_id)

    if result is None:
        raise HTTPException(status_code=404, detail=f"Query not found: {request.query_id}")

    if result.status != "completed":
        raise HTTPException(status_code=400, detail="Query must be completed before exporting")

    try:
        # Export to file
        file_path = export_service.export_result(result, request.format)
        filename = os.path.basename(file_path)

        # Add to history (auto-save query with export)
        history_service.add_query(result, export_filename=filename)

        return ExportResponse(
            download_url=f"/exports/{filename}",
            filename=filename,
            format=request.format
        )

    except ImportError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@app.get("/api/query/export/download/{filename}")
async def download_export(filename: str):
    """
    Download an exported file

    Returns the exported file for download.
    """
    file_path = os.path.join("exports", filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )


# ========== Query History Endpoints ==========

@app.get("/api/history")
async def get_history(limit: int = 10):
    """
    Get query history (lightweight metadata only)

    Returns a list of recent queries with basic metadata.
    Limited to most recent queries for performance.
    """
    if limit < 1 or limit > 50:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 50")

    return history_service.list_queries(limit=limit)


@app.get("/api/history/stats")
async def get_history_stats():
    """
    Get statistics about query history

    Returns counts, averages, and other useful statistics.
    """
    return history_service.get_stats()


@app.post("/api/history/sync")
async def sync_history():
    """
    Sync history index from results/ folder

    Rebuilds the history index by scanning all results/ folders.
    Useful for recovering history or syncing after manual changes.
    """
    history_service.sync_from_results_folder()
    stats = history_service.get_stats()
    return {
        "message": "History synced successfully",
        "stats": stats,
        "success": True
    }


@app.get("/api/history/{query_id}", response_model=QueryResult)
async def get_history_query(query_id: str):
    """
    Get full query result from history

    Returns the complete query result including all data.
    """
    result = history_service.get_query(query_id)

    if result is None:
        raise HTTPException(status_code=404, detail=f"Query not found in history: {query_id}")

    return result


@app.delete("/api/history/{query_id}")
async def delete_history_query(query_id: str):
    """
    Delete a query from history

    Removes the query metadata and associated export files.
    """
    success = history_service.delete_query(query_id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Query not found in history: {query_id}")

    return {"message": f"Query {query_id} deleted successfully", "success": True}


@app.delete("/api/history")
async def clear_history():
    """
    Clear all query history (use with caution!)

    Deletes all queries and associated files from history.
    """
    history_service.clear_all()
    return {"message": "All history cleared successfully", "success": True}


@app.websocket("/ws/{query_id}")
async def websocket_endpoint(websocket: WebSocket, query_id: str):
    """WebSocket endpoint for real-time query progress updates"""
    await manager.connect(websocket, query_id)

    try:
        await websocket.send_json({
            "type": "connected",
            "query_id": query_id,
            "message": "Connected to query progress updates",
            "timestamp": datetime.utcnow().isoformat()
        })

        buffered_logs = query_service.get_buffered_logs(query_id)
        for log in buffered_logs:
            await websocket.send_json(log)

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                if data == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })
            except asyncio.TimeoutError:
                continue

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
        manager.disconnect(websocket)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code
        }
    )


def start_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Start the FastAPI server"""
    uvicorn.run(
        "backend.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )


if __name__ == "__main__":
    start_server(reload=True)
