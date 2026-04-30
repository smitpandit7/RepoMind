import os
import git
import chromadb
from pathlib import Path
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from openai import OpenAI
import json
import re

load_dotenv()

SUPPORTED_EXTENSIONS = [
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".cs", ".kt", ".swift", ".scala", ".r",
    ".md", ".txt", ".html", ".css", ".scss", ".sass",
    ".dart", ".yaml", ".yml", ".json", ".toml", ".xml", ".sh", ".bash"
]

SKIP_DIRS = {
    # Universal
    ".git", "__pycache__", "build", "dist", ".cache", ".tmp",
    # JS/TS
    "node_modules", ".next", ".nuxt", "out",
    # Python
    ".venv", "venv", "env", ".env", "*.egg-info", ".pytest_cache", ".mypy_cache",
    # Java/Kotlin/Android
    ".gradle", ".idea", "android/build", "app/build",
    # Flutter/Dart
    ".dart_tool", ".flutter-plugins", ".flutter-plugins-dependencies",
    # iOS/macOS/Windows/Linux (Flutter platform folders)
    "windows", "linux", "macos", "ios/Pods",
    # Rust
    "target",
    # Ruby
    ".bundle", "vendor/bundle",
    # General
    "coverage", ".nyc_output", "logs", "*.log"
}

# Language-specific function/class boundary patterns
BOUNDARY_PATTERNS = {
    # Python
    ".py": re.compile(r'^\s*(def |async def |class )'),
    # JavaScript / TypeScript / JSX / TSX
    ".js":  re.compile(r'^\s*(function |const \w+ ?= ?(async ?)?\(|class |export (default )?(function|class|const)|async function )'),
    ".ts":  re.compile(r'^\s*(function |const \w+ ?= ?(async ?)?\(|class |interface |type \w+ ?=|export (default )?(function|class|const)|async function )'),
    ".jsx": re.compile(r'^\s*(function |const \w+ ?= ?(async ?)?\(|class |export (default )?(function|class|const))'),
    ".tsx": re.compile(r'^\s*(function |const \w+ ?= ?(async ?)?\(|class |interface |export (default )?(function|class|const))'),
    # Java / Kotlin
    ".java": re.compile(r'^\s*(public |private |protected |static |void |class |interface |enum |@\w+\s*\n?\s*public )'),
    ".kt":   re.compile(r'^\s*(fun |class |object |interface |data class |sealed class |abstract class )'),
    # C / C++
    ".c":   re.compile(r'^[a-zA-Z_][\w\s\*]+\('),
    ".h":   re.compile(r'^[a-zA-Z_][\w\s\*]+\('),
    ".cpp": re.compile(r'^\s*(void |int |bool |auto |string |class |struct |template |namespace )'),
    ".hpp": re.compile(r'^\s*(void |int |bool |auto |string |class |struct |template |namespace )'),
    # Go
    ".go": re.compile(r'^\s*(func |type \w+ (struct|interface))'),
    # Rust
    ".rs": re.compile(r'^\s*(fn |pub fn |async fn |pub async fn |impl |trait |struct |enum |mod )'),
    # Ruby
    ".rb": re.compile(r'^\s*(def |class |module )'),
    # PHP
    ".php": re.compile(r'^\s*(function |class |interface |trait |public |private |protected )'),
    # C#
    ".cs": re.compile(r'^\s*(public |private |protected |static |void |class |interface |enum |namespace |async )'),
    # Swift
    ".swift": re.compile(r'^\s*(func |class |struct |enum |protocol |extension |var |let )'),
    # Scala
    ".scala": re.compile(r'^\s*(def |class |object |trait |case class |abstract class )'),
    # Dart
    ".dart": re.compile(r'^\s*(void |Widget |Future |Stream |class |abstract class |mixin |extension )'),
    # Shell
    ".sh":   re.compile(r'^\s*\w[\w_-]*\s*\(\s*\)'),
    ".bash": re.compile(r'^\s*\w[\w_-]*\s*\(\s*\)'),
}

# Fallback pattern for unknown extensions
GENERIC_BOUNDARY = re.compile(
    r'^\s*(def |class |function |func |fn |public |private |void |async )'
)

model = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./.chroma_db")

openrouter = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY")
)

MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",      # keep, just rate limited
    "google/gemma-3-27b-it:free",                   # gemma 27b (more available)
    "mistralai/mistral-7b-instruct:free",            # very reliable free model
    "deepseek/deepseek-r1-distill-llama-70b:free",  # deepseek distill, usually available
    "nousresearch/hermes-3-llama-3.1-405b:free",    # large, good fallback
]


def call_agent(prompt: str) -> str:
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
    return ""


def clone_repo(repo_url: str, clone_path: str = "./.temp_repo") -> str:
    if os.path.exists(clone_path):
        import shutil
        shutil.rmtree(clone_path)
    print(f"Cloning {repo_url}...")
    git.Repo.clone_from(repo_url, clone_path)
    print("Cloning done!")
    return clone_path


def analyze_repo(repo_path: str, files: list[dict]) -> dict:
    """Agent step 1 — analyze the repo structure and decide what matters."""
    file_list = "\n".join([f["path"].replace(repo_path, "") for f in files[:50]])

    prompt = f"""You are a code analyst. Look at this list of files from a repository and answer in JSON only.

Files:
{file_list}

Respond with ONLY a JSON object like this (no markdown, no explanation):
{{
  "project_type": "django/react/springboot/cli-tool/library/etc",
  "main_language": "python/javascript/java/go/rust/etc",
  "important_dirs": ["src", "lib", "app", "core"],
  "skip_dirs": ["build", "dist", "target"],
  "key_files": ["main.py", "package.json", "README.md"]
}}"""

    result = call_agent(prompt)
    try:
        result = result.strip()
        if "```" in result:
            result = re.sub(r"```(?:json)?", "", result).strip().strip("```")
        return json.loads(result)
    except:
        return {
            "project_type": "unknown",
            "main_language": "unknown",
            "important_dirs": [],
            "skip_dirs": list(SKIP_DIRS),
            "key_files": []
        }


def load_files(repo_path: str, skip_dirs: list = None) -> list[dict]:
    skip = set(SKIP_DIRS)
    if skip_dirs:
        skip.update(skip_dirs)

    files = []
    for path in Path(repo_path).rglob("*"):
        # Skip if any path part matches a skip dir
        if any(part in skip for part in path.parts):
            continue
        if path.suffix in SUPPORTED_EXTENSIONS:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                if content.strip():
                    files.append({
                        "path": str(path),
                        "filename": path.name,
                        "extension": path.suffix,
                        "content": content
                    })
            except Exception as e:
                print(f"Skipping {path}: {e}")
    print(f"Loaded {len(files)} files")
    return files


def smart_chunk_file(file: dict, chunk_size: int = 60, overlap: int = 10) -> list[dict]:
    """
    Split at language-aware function/class boundaries.
    Falls back to generic pattern or line-based chunking for unknown file types.
    """
    content = file["content"]
    ext = file.get("extension", Path(file["path"]).suffix)
    lines = content.splitlines()
    chunks = []

    # Pick the right boundary pattern for this file's language
    boundary_pattern = BOUNDARY_PATTERNS.get(ext, GENERIC_BOUNDARY)

    boundary_lines = [0]
    for i, line in enumerate(lines):
        if boundary_pattern.match(line) and i > 0:
            boundary_lines.append(i)
    boundary_lines.append(len(lines))

    for idx in range(len(boundary_lines) - 1):
        start = boundary_lines[idx]
        end = boundary_lines[idx + 1]
        section_lines = lines[start:end]

        if len(section_lines) <= chunk_size:
            chunk_text = "\n".join(section_lines)
            if chunk_text.strip():
                chunks.append({
                    "text": chunk_text,
                    "filename": file["filename"],
                    "filepath": file["path"],
                    "extension": ext,
                    "start_line": start + 1,
                    "end_line": end,
                    "chunk_type": "function_block"
                })
        else:
            # Large block — slide a window over it
            i = 0
            while i < len(section_lines):
                chunk_lines = section_lines[i:i + chunk_size]
                chunk_text = "\n".join(chunk_lines)
                if chunk_text.strip():
                    chunks.append({
                        "text": chunk_text,
                        "filename": file["filename"],
                        "filepath": file["path"],
                        "extension": ext,
                        "start_line": start + i + 1,
                        "end_line": start + i + len(chunk_lines),
                        "chunk_type": "code_block"
                    })
                i += chunk_size - overlap

    return chunks


def tag_chunk(chunk: dict, project_type: str, main_language: str) -> dict:
    """Agent step 2 — add semantic tags to each chunk."""
    prompt = f"""You are a code tagger. Look at this code chunk and respond with ONLY a JSON object (no markdown, no explanation).

File: {chunk['filename']}
Language: {main_language}
Project type: {project_type}
Code:
{chunk['text'][:500]}

Respond ONLY with:
{{
  "topic": "authentication|routing|database|ui|api|state_management|config|utility|testing|models|networking|parsing|error_handling|other",
  "importance": "high|medium|low",
  "summary": "one sentence describing what this code does"
}}"""

    result = call_agent(prompt)
    try:
        result = result.strip()
        if "```" in result:
            result = re.sub(r"```(?:json)?", "", result).strip().strip("```")
        tags = json.loads(result)
        chunk["topic"] = tags.get("topic", "other")
        chunk["importance"] = tags.get("importance", "medium")
        chunk["summary"] = tags.get("summary", "")
    except:
        chunk["topic"] = "other"
        chunk["importance"] = "medium"
        chunk["summary"] = ""
    return chunk


def ingest_repo(repo_url: str, collection_name: str = "github_rag"):
    clone_path = clone_repo(repo_url)

    print("Loading files (initial pass)...")
    files = load_files(clone_path)

    print("Agent analyzing repo structure...")
    repo_info = analyze_repo(clone_path, files)
    print(f"Detected: {repo_info['project_type']} project in {repo_info['main_language']}")

    # Second pass — now with agent-suggested skip dirs merged in
    print("Loading files (filtered pass)...")
    files = load_files(clone_path, skip_dirs=repo_info.get("skip_dirs", []))

    try:
        client.delete_collection(name=collection_name)
        print("Old collection deleted, starting fresh...")
    except:
        pass

    print("Smart chunking files...")
    all_chunks = []
    for file in files:
        all_chunks.extend(smart_chunk_file(file))
    print(f"Total chunks: {len(all_chunks)}")

    print("Agent tagging chunks (adding semantic metadata)...")
    tagged_chunks = []
    main_language = repo_info.get("main_language", "unknown")
    project_type = repo_info.get("project_type", "unknown")

    for i, chunk in enumerate(all_chunks):
        if i % 20 == 0:
            print(f"  Tagging chunk {i+1}/{len(all_chunks)}...")
        tagged = tag_chunk(chunk, project_type, main_language)
        tagged_chunks.append(tagged)

    print("Generating embeddings...")
    texts = [c["text"] for c in tagged_chunks]
    embeddings = model.encode(texts, show_progress_bar=True)

    collection = client.get_or_create_collection(name=collection_name)

    batch_size = 100
    for i in range(0, len(tagged_chunks), batch_size):
        batch = tagged_chunks[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]
        collection.add(
            ids=[f"chunk_{i+j}" for j in range(len(batch))],
            embeddings=batch_embeddings.tolist(),
            documents=[c["text"] for c in batch],
            metadatas=[{
                "filename": c["filename"],
                "filepath": c["filepath"],
                "extension": c.get("extension", ""),
                "start_line": c["start_line"],
                "end_line": c["end_line"],
                "chunk_type": c.get("chunk_type", "code_block"),
                "topic": c.get("topic", "other"),
                "importance": c.get("importance", "medium"),
                "summary": c.get("summary", "")
            } for c in batch]
        )

    print(f"\nIngestion complete! {len(tagged_chunks)} chunks indexed and ready to query.")
    return len(tagged_chunks)