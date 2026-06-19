from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from typing import List, Optional
import os, shutil, json, uuid

from dotenv import load_dotenv
from together import Together
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import CharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader

load_dotenv()
client = Together(api_key=os.getenv("TOGETHER_API_KEY"))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VECTOR_STORE_PATH = "faiss_vector_store"
UPLOAD_FOLDER     = "uploaded_documents"
METADATA_FILE     = "document_metadata.json"
ALLOWED_EXT       = {".pdf", ".docx", ".xlsx"}
# L2 distance threshold — lower means more similar.
# If best match > 1.0 the query is considered out-of-context.
RELEVANCE_THRESHOLD = 1.0

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

embeddings   = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")
vector_store = None


# ─── Metadata helpers ─────────────────────────────────────────────────────────

def load_meta() -> dict:
    if Path(METADATA_FILE).exists():
        try:
            with open(METADATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"folders": {}, "file_folders": {}, "queries": []}


def save_meta(data: dict):
    with open(METADATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def record_query(question: str, sources: list):
    """Append a query to the metadata, keeping the most recent 100."""
    meta = load_meta()
    entry = {
        "id":        str(uuid.uuid4()),
        "question":  question,
        "timestamp": datetime.now().isoformat() + "Z",
        "sources":   sources,
    }
    queries = meta.get("queries", [])
    queries.insert(0, entry)
    meta["queries"] = queries[:100]
    save_meta(meta)


# ─── Vector store ─────────────────────────────────────────────────────────────

def load_vector_store():
    global vector_store
    try:
        vector_store = FAISS.load_local(
            VECTOR_STORE_PATH, embeddings, allow_dangerous_deserialization=True
        )
        print("Vector store loaded.")
    except Exception as e:
        print(f"No vector store on disk ({e}). Will create on first upload.")
        vector_store = None

load_vector_store()


# ─── Text extraction ──────────────────────────────────────────────────────────

def extract_texts(file_path: str, ext: str) -> List[str]:
    splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=100)

    if ext == ".pdf":
        docs   = PyPDFLoader(file_path).load()
        chunks = splitter.split_documents(docs)
        return [c.page_content for c in chunks if c.page_content.strip()]

    if ext == ".docx":
        from docx import Document as DocxDoc
        doc  = DocxDoc(file_path)
        text = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        if not text:
            raise HTTPException(422, "DOCX file appears to be empty.")
        return splitter.split_text(text)

    if ext == ".xlsx":
        import openpyxl
        wb, texts = openpyxl.load_workbook(file_path, read_only=True, data_only=True), []
        for sheet in wb.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip()]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                texts.extend(splitter.split_text(f"[Sheet: {sheet.title}]\n" + "\n".join(rows)))
        wb.close()
        if not texts:
            raise HTTPException(422, "XLSX file appears to be empty.")
        return texts

    raise HTTPException(400, f"Unsupported file type: {ext}")


# ─── Pydantic models ──────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str

class FolderCreate(BaseModel):
    name: str

class FolderRename(BaseModel):
    name: str


# ═══════════════════════════════════════════════════════════════════════════════
# FOLDER APIs
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/folders/")
async def list_folders():
    meta         = load_meta()
    folders_data = meta.get("folders", {})
    file_folders = meta.get("file_folders", {})

    counts: dict = {}
    for fname, fid in file_folders.items():
        if (Path(UPLOAD_FOLDER) / fname).exists():
            counts[fid] = counts.get(fid, 0) + 1

    result = [
        {
            "id":            fid,
            "name":          f["name"],
            "documentCount": counts.get(fid, 0),
            "createdAt":     f["createdAt"],
        }
        for fid, f in folders_data.items()
    ]
    return sorted(result, key=lambda x: x["createdAt"])


@app.post("/folders/")
async def create_folder(body: FolderCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Folder name cannot be empty.")
    meta    = load_meta()
    fid     = str(uuid.uuid4())
    created = datetime.now().isoformat() + "Z"
    meta.setdefault("folders", {})[fid] = {"id": fid, "name": name, "createdAt": created}
    save_meta(meta)
    return {"id": fid, "name": name, "documentCount": 0, "createdAt": created}


@app.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, body: FolderRename):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Folder name cannot be empty.")
    meta = load_meta()
    if folder_id not in meta.get("folders", {}):
        raise HTTPException(404, "Folder not found.")
    meta["folders"][folder_id]["name"] = name
    save_meta(meta)
    return {"id": folder_id, "name": name}


@app.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str):
    meta = load_meta()
    if folder_id not in meta.get("folders", {}):
        raise HTTPException(404, "Folder not found.")
    del meta["folders"][folder_id]
    meta["file_folders"] = {
        fname: fid
        for fname, fid in meta.get("file_folders", {}).items()
        if fid != folder_id
    }
    save_meta(meta)
    return {"message": "Folder deleted."}


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT APIs
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/upload/")
async def upload_document(
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None),
):
    global vector_store

    filename  = file.filename or ""
    ext       = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported type '{ext}'. Allowed: PDF, DOCX, XLSX.")

    safe_name = Path(filename).name
    file_path = os.path.join(UPLOAD_FOLDER, safe_name)

    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        texts = extract_texts(file_path, ext)
        if not texts:
            raise HTTPException(422, "Could not extract text from file.")

        new_store = FAISS.from_texts(texts, embedding=embeddings)
        if vector_store is None:
            vector_store = new_store
        else:
            vector_store.merge_from(new_store)
        vector_store.save_local(VECTOR_STORE_PATH)

        if folder_id:
            meta = load_meta()
            if folder_id in meta.get("folders", {}):
                meta.setdefault("file_folders", {})[safe_name] = folder_id
                save_meta(meta)

        print(f"Uploaded: {safe_name} | folder={folder_id} | {len(texts)} chunks")
        return {
            "filename": safe_name,
            "message":  f"'{safe_name}' uploaded and indexed ({len(texts)} chunks).",
            "chunks":   len(texts),
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Upload error: {e}")
        raise HTTPException(500, f"Failed to process file: {e}")
    finally:
        file.file.close()


@app.get("/documents/")
async def list_documents():
    meta         = load_meta()
    file_folders = meta.get("file_folders", {})
    folders_data = meta.get("folders", {})

    docs = []
    upload_path = Path(UPLOAD_FOLDER)
    if upload_path.exists():
        files = sorted(
            [f for f in upload_path.iterdir() if f.is_file()],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for fp in files:
            stat      = fp.stat()
            ext       = fp.suffix.lstrip(".").lower()
            folder_id = file_folders.get(fp.name)
            folder_nm = folders_data.get(folder_id, {}).get("name") if folder_id else None
            docs.append({
                "id":         fp.name,
                "name":       fp.name,
                "type":       ext if ext in ["pdf", "docx", "xlsx"] else "pdf",
                "size":       stat.st_size,
                "folderId":   folder_id,
                "folderName": folder_nm,
                "uploadedAt": datetime.fromtimestamp(stat.st_mtime).isoformat() + "Z",
                "indexed":    True,
            })
    return docs


@app.delete("/documents/{filename}")
async def delete_document(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename.")
    file_path = Path(UPLOAD_FOLDER) / filename
    if not file_path.exists():
        raise HTTPException(404, "File not found.")
    file_path.unlink()
    meta = load_meta()
    meta["file_folders"].pop(filename, None)
    save_meta(meta)
    return {"message": f"'{filename}' deleted."}


@app.get("/stats/")
async def get_stats():
    upload_path = Path(UPLOAD_FOLDER)
    doc_count   = 0
    total_size  = 0
    if upload_path.exists():
        for f in upload_path.iterdir():
            if f.is_file():
                doc_count  += 1
                total_size += f.stat().st_size

    meta        = load_meta()
    today       = datetime.now().date().isoformat()
    queries_today = sum(
        1 for q in meta.get("queries", [])
        if q.get("timestamp", "").startswith(today)
    )

    return {
        "totalDocuments":   doc_count,
        "totalFolders":     len(meta.get("folders", {})),
        "indexedDocuments": doc_count,
        "aiQueriesToday":   queries_today,
        "storageUsedMb":    round(total_size / (1024 * 1024), 2),
        "storageTotalMb":   10240,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY APIs
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/queries/")
async def get_recent_queries(limit: int = 10):
    meta = load_meta()
    return meta.get("queries", [])[:limit]


@app.post("/query/")
async def ask_question(request: QueryRequest):
    global vector_store

    if vector_store is None:
        raise HTTPException(503, detail="no_documents")

    question = request.question.strip()
    if not question:
        raise HTTPException(400, "Question cannot be empty.")

    # ── Relevance check ──────────────────────────────────────────────────────
    # similarity_search_with_score returns (doc, L2_distance).
    # Lower L2 = more similar. For normalized embeddings max L2 ≈ 1.41.
    try:
        docs_scores = vector_store.similarity_search_with_score(question, k=3)
    except Exception as e:
        raise HTTPException(500, f"Search error: {e}")

    if not docs_scores:
        raise HTTPException(422, detail="out_of_context")

    best_score = min(score for _, score in docs_scores)
    print(f"Query: '{question[:60]}' | best L2={best_score:.3f}")

    if best_score > RELEVANCE_THRESHOLD:
        raise HTTPException(422, detail="out_of_context")

    # ── Build context from relevant docs ────────────────────────────────────
    relevant_docs = [doc for doc, _ in docs_scores]
    context       = "\n\n".join(d.page_content for d in relevant_docs)

    # ── Call LLM ────────────────────────────────────────────────────────────
    response = client.chat.completions.create(
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a document assistant. Answer the user's question using ONLY "
                    "the provided context from their uploaded documents. "
                    "If the context does not contain the answer, respond with exactly: "
                    "'I could not find this information in the uploaded documents.'"
                ),
            },
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
        ],
    )

    answer  = response.choices[0].message.content
    sources = list({d.metadata.get("source", "Unknown") for d in relevant_docs})

    # ── Save query to history ────────────────────────────────────────────────
    record_query(question, sources)

    return {"answer": answer, "sources": sources}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
