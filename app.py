from flask import Flask, request, jsonify, render_template
from config import settings
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import pytesseract
from paddleocr import PaddleOCR
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import faiss
from langchain_groq import ChatGroq
import os

app = Flask(__name__)

# Initialize PaddleOCR (English; change to 'hi' for Hindi, 'ta' for Tamil, etc.)
paddle_ocr = PaddleOCR(use_angle_cls=True, lang='en')

# Embedding setup
embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

# Groq LLM setup
llm = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0,
    max_tokens=None,
    reasoning_format="parsed",
    timeout=None,
    max_retries=4,
)

# Global FAISS index + docs
index = None
docs = []

# -------------------------------
# PDF ingestion with PaddleOCR
# -------------------------------
def extract_text_from_pdf(pdf_path, pdf_id):
    doc = fitz.open(pdf_path)
    text_chunks = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text()

        # If no native text, run OCR
        if not text.strip():
            pix = page.get_pixmap()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            try:
                result = paddle_ocr.ocr(np.array(img))
                text = " ".join([line[1][0] for line in result[0]]) if result else ""
            except Exception as e:
                print(f"PaddleOCR failed, fallback to Tesseract: {e}")
                text = pytesseract.image_to_string(img)

        text_chunks.append((pdf_id, page_num+1, text))
    return text_chunks

def chunk_text(text_chunks, filename, chunk_size=800, chunk_overlap=200):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
    docs_local = []
    for pdf_id, page_num, text in text_chunks:
        for chunk in splitter.split_text(text):
            docs_local.append({
                "content": chunk,
                "metadata": {"pdf_id": pdf_id, "filename": filename, "page": page_num}
            })
    return docs_local

def embed_documents(docs_local):
    texts = [d["content"] for d in docs_local]
    embeddings = embedder.encode(texts, convert_to_numpy=True)
    return embeddings, docs_local

def build_or_extend_faiss_index(embeddings):
    global index
    dim = embeddings.shape[1]
    if index is None:
        index = faiss.IndexHNSWFlat(dim, 32)
    index.add(embeddings)

def retrieve(query, k=5):
    q_emb = embedder.encode([query], convert_to_numpy=True)
    D, I = index.search(q_emb, k)
    results = [docs[i] for i in I[0]]
    return results

def answer_query(query):
    retrieved = retrieve(query)
    context = "\n".join([f"[{r['metadata']['filename']} p.{r['metadata']['page']}] {r['content']}" for r in retrieved])
    prompt = f"Answer the question based on the context below.\n\nContext:\n{context}\n\nQuestion: {query}\nAnswer with citations (filename + page numbers)."
    
    # Use Groq LLM correctly
    response = llm.invoke(prompt)
    return response.content

# -------------------------------
# Flask Routes
# -------------------------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload_pdf():
    global docs
    file = request.files["file"]
    pdf_path = f"./uploads/{file.filename}"
    file.save(pdf_path)

    text_chunks = extract_text_from_pdf(pdf_path, pdf_id=file.filename)
    docs_local = chunk_text(text_chunks, filename=file.filename)
    embeddings, docs_local = embed_documents(docs_local)
    build_or_extend_faiss_index(embeddings)

    docs.extend(docs_local)

    return jsonify({"status": f"{file.filename} ingested successfully", "pages": len(text_chunks)})

@app.route("/ask", methods=["POST"])
def ask_question():
    query = request.json.get("query")
    if index is None:
        return jsonify({"error": "No documents ingested yet"})
    response = answer_query(query)
    return jsonify({"answer": response})

if __name__ == "__main__":
    os.makedirs("./uploads", exist_ok=True)
    app.run(debug=True)
