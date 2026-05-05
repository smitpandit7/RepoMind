import os
import threading
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app.ingestion.ingestor import ingest_repo, client 
from app.query.query_engine import query_repo

app = FastAPI(
    title="GitHub RAG API",
    description="Ask questions about any GitHub repository",
    version="1.0.0"
)

# Serve the static frontend files
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class IngestRequest(BaseModel):
    repo_url: str
    collection_name: str = "github_rag"

class QueryRequest(BaseModel):
    question: str
    collection_name: str = "github_rag"
    top_k: int = 5



_status_lock = threading.Lock()
ingestion_status = {}

def set_status(name: str, value: str):
    with _status_lock:
        ingestion_status[name] = value

def get_status(name: str) -> str:
    with _status_lock:
        return ingestion_status.get(name, "not_started")

def run_ingestion(repo_url: str, collection_name: str):
    try:
        set_status(collection_name, "cloning")
        count = ingest_repo(
            repo_url, collection_name,
            on_status=lambda s: set_status(collection_name, s)
        )
        set_status(collection_name, f"done|{count}")
    except Exception as e:
        set_status(collection_name, f"failed|{str(e)}")


@app.get("/")
def root():
    return FileResponse("frontend/index.html")


@app.post("/ingest")
def ingest(request: IngestRequest, background_tasks: BackgroundTasks):
    set_status(request.collection_name, "starting")
    background_tasks.add_task(
        run_ingestion,
        request.repo_url,
        request.collection_name
    )
    return {
        "message": "Ingestion started in background",
        "repo_url": request.repo_url,
        "collection_name": request.collection_name,
        "tip": f"Check /status/{request.collection_name} to see progress"
    }


@app.get("/status/{collection_name}")
def status(collection_name: str):
    s = get_status(collection_name)  # uses the lock
    return {"collection_name": collection_name, "status": s}


@app.post("/query")
def query(request: QueryRequest):
    try:
        collection = client.get_collection(name=request.collection_name)
    except Exception:
        raise HTTPException(
            status_code=404,
            detail=f"Collection '{request.collection_name}' not found. Run /ingest first."
        )
    try:
        result = query_repo(
            question=request.question,
            collection_name=request.collection_name,
            top_k=request.top_k
        )
        return {"question": request.question, "answer": result["answer"], "sources": result["sources"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))