import chromadb
import re
import time
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from openai import OpenAI
import os

load_dotenv()

model = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./.chroma_db")

openrouter = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-7b-instruct:free",
    "deepseek/deepseek-r1-distill-llama-70b:free",
]


def call_llm(prompt: str) -> str:
    for m in MODELS:
        try:
            response = openrouter.chat.completions.create(
                model=m,
                messages=[{"role": "user", "content": prompt}],
                timeout=30
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Model {m} failed: {e}, trying next...")
            time.sleep(1)
    return "All models are currently rate limited. Please try again in a few minutes."


def extract_filename_hint(question: str) -> str | None:
    """
    Detect if the user is asking about a specific file.
    e.g. 'explain widget_bottom_cart_card.dart' → 'widget_bottom_cart_card.dart'
    """
    # Match any word ending with a known code/config extension
    pattern = r'\b([\w_\-]+\.(dart|py|js|ts|jsx|tsx|java|kt|go|rs|cpp|c|cs|rb|swift|yaml|yml|json|html|css|md))\b'
    match = re.search(pattern, question, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def retrieve_chunks(collection, question: str, top_k: int = 5) -> tuple[list, list]:
    """
    Smart retrieval:
    - If question mentions a specific filename → fetch ALL chunks from that file
      + top semantic matches for supporting context
    - Otherwise → pure semantic top-k
    """
    filename_hint = extract_filename_hint(question)

    if filename_hint:
        print(f"  [Retrieval] File-specific query detected: {filename_hint}")

        # Get ALL chunks from the mentioned file
        file_results = collection.get(
            where={"filename": filename_hint},
            include=["documents", "metadatas"]
        )

        file_chunks = file_results.get("documents", [])
        file_metas = file_results.get("metadatas", [])

        if file_chunks:
            print(f"  [Retrieval] Found {len(file_chunks)} chunks for {filename_hint}")

            # Also grab a few semantic results for broader context (other related files)
            question_embedding = model.encode(question).tolist()
            semantic_results = collection.query(
                query_embeddings=[question_embedding],
                n_results=top_k,
                where={"filename": {"$ne": filename_hint}}  # exclude already-fetched file
            )
            extra_chunks = semantic_results["documents"][0]
            extra_metas = semantic_results["metadatas"][0]

            # File chunks first (full file), then supporting context
            all_chunks = file_chunks + extra_chunks[:2]
            all_metas = file_metas + extra_metas[:2]
            return all_chunks, all_metas

        else:
            print(f"  [Retrieval] No chunks found for {filename_hint}, falling back to semantic search")

    # Default: pure semantic search
    print(f"  [Retrieval] Semantic search, top_k={top_k}")
    question_embedding = model.encode(question).tolist()
    results = collection.query(
        query_embeddings=[question_embedding],
        n_results=top_k
    )
    return results["documents"][0], results["metadatas"][0]


def build_context(chunks: list, metadatas: list) -> str:
    context = ""
    for chunk, meta in zip(chunks, metadatas):
        context += f"\n--- File: {meta['filename']} (lines {meta['start_line']}-{meta['end_line']}) ---\n"
        context += chunk + "\n"
    return context


def build_prompt(question: str, context: str) -> str:
    return f"""You are an expert code assistant analyzing a GitHub codebase.

IMPORTANT FORMATTING RULES:
- If the user asks to EXPLAIN a file, function, or code — for each section:
  1. Show the code block first using ```language
  2. Below it, write a clear explanation in bullet points
  Repeat for every logical section of the file.

- If the user asks a GENERAL question (how does X work, where is Y, what does Z do):
  Answer in clear paragraphs with **bold** for important terms, bullet points for lists,
  and `backticks` for inline code references.

- Always mention filename and line numbers when referencing code.
- Be thorough — if you have the full file, explain ALL parts of it, not just the imports.
- Never dump a wall of text without structure.

Code context:
{context}

Question: {question}

Answer:"""


def query_repo(question: str, collection_name: str = "github_rag", top_k: int = 5) -> dict:
    collection = client.get_collection(name=collection_name)

    chunks, metadatas = retrieve_chunks(collection, question, top_k)

    # Debug — shows exactly what was sent to the LLM
    print(f"  [Context] Chunks passed to LLM:")
    for m in metadatas:
        print(f"    - {m['filename']} L{m['start_line']}-{m['end_line']}")

    context = build_context(chunks, metadatas)
    prompt = build_prompt(question, context)
    answer = call_llm(prompt)

    return {
        "answer": answer,
        "sources": [
            {
                "filename": m["filename"],
                "filepath": m["filepath"],
                "start_line": m["start_line"],
                "end_line": m["end_line"]
            }
            for m in metadatas
        ]
    }