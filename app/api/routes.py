import os
import shutil
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app.ingestion.ingestor import clone_repo, load_files, smart_chunk_file, model, client
from app.query.query_engine import query_repo
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

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

ingestion_status = {}


def run_ingestion(repo_url: str, collection_name: str):
    try:
        ingestion_status[collection_name] = "cloning"
        clone_path = clone_repo(repo_url)

        ingestion_status[collection_name] = "reading_files"
        files = load_files(clone_path)

        ingestion_status[collection_name] = f"chunking|{len(files)}"
        all_chunks = []
        for file in files:
            all_chunks.extend(smart_chunk_file(file))

        ingestion_status[collection_name] = f"embedding|{len(all_chunks)}"

        try:
            client.delete_collection(name=collection_name)
            print("Old collection deleted, starting fresh...")
        except:
            pass

        collection = client.get_or_create_collection(name=collection_name)
        texts = [c["text"] for c in all_chunks]
        embeddings = model.encode(texts, show_progress_bar=True)

        batch_size = 100
        batches = list(range(0, len(all_chunks), batch_size))
        total_batches = len(batches)

        for batch_num, i in enumerate(batches):
            batch = all_chunks[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            collection.add(
                ids=[f"chunk_{i+j}" for j in range(len(batch))],
                embeddings=batch_embeddings.tolist(),
                documents=[c["text"] for c in batch],
                metadatas=[{
                    "filename": c["filename"],
                    "filepath": c["filepath"],
                    "start_line": c["start_line"],
                    "end_line": c["end_line"]
                } for c in batch]
            )
            ingestion_status[collection_name] = f"storing|{batch_num+1}|{total_batches}|{len(all_chunks)}"

        ingestion_status[collection_name] = f"done|{len(all_chunks)}"
        print("Ingestion complete! Repo is indexed and ready to query.")
    except Exception as e:
        ingestion_status[collection_name] = f"failed|{str(e)}"
        print(f"Ingestion failed: {e}")


@app.get("/")
def root():
    return FileResponse("frontend/index.html")


@app.post("/ingest")
def ingest(request: IngestRequest, background_tasks: BackgroundTasks):
    ingestion_status[request.collection_name] = "starting"
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
    s = ingestion_status.get(collection_name, "not_started")
    return {
        "collection_name": collection_name,
        "status": s
    }


@app.post("/query")
def query(request: QueryRequest):
    try:
        result = query_repo(
            question=request.question,
            collection_name=request.collection_name,
            top_k=request.top_k
        )
        return {
            "question": request.question,
            "answer": result["answer"],
            "sources": result["sources"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))