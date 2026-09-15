import pymupdf
import os
import re
from typing import Tuple, List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from app.config import settings

# Configurable embedding model
embeddings = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)

def get_project_collection_name(project_id: str) -> str:
    """Derive sanitized, isolated collection name per project."""
    clean_id = re.sub(r'[^a-zA-Z0-9_]', '_', project_id).lower()
    return f"proj_{clean_id}"

def get_vectorstore(project_id: str) -> Chroma:
    """Retrieve Chroma vectorstore for the project."""
    collection_name = get_project_collection_name(project_id)
    return Chroma(
        collection_name=collection_name,
        persist_directory=settings.CHROMA_PERSIST_DIR,
        embedding_function=embeddings
    )

def remove_existing_document_chunks(project_id: str, original_filename: str) -> int:
    """
    Remove previously indexed chunks for this document in the project collection
    to prevent duplicate chunks upon re-upload.
    """
    try:
        vectorstore = get_vectorstore(project_id)
        # Delete chunks where source matches original_filename
        vectorstore._collection.delete(where={"source": original_filename})
        return 1
    except Exception:
        return 0

def detect_section_header(text: str) -> str:
    """Identify prominent AUTOSAR document section headers."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:5]:
        if re.match(r'^(?:[0-9]+\.)+[0-9]*\s+[A-Z]', line) or re.match(r'^[0-9]+\s+[A-Z][A-Za-z\s]{3,40}$', line):
            return line[:60]
        if line.isupper() and 4 < len(line) < 50:
            return line
    return "General Architecture Specification"

def process_and_store_document(
    file_path: str,
    project_id: str,
    original_filename: str
) -> Tuple[int, int, int]:
    """
    Ingest AUTOSAR HLD document:
    - Deduplicates existing chunks for this filename
    - Page-by-page extraction with section detection
    - OCR fallback for scanned/image pages
    - Metadata tagging with page, section, project_id, and source
    - Storage into isolated, project-specific ChromaDB collection
    Returns: (page_count, chunk_count, ocr_pages_count)
    """
    # 1. Deduplicate: remove any previous chunks for this file in this project collection
    remove_existing_document_chunks(project_id, original_filename)

    doc = pymupdf.open(file_path)
    page_count = len(doc)
    ocr_pages_count = 0
    all_chunks: List[Document] = []
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=150,
        length_function=len
    )
    
    current_section = "General Architecture Overview"
    
    for page_idx in range(page_count):
        page_num = page_idx + 1
        page = doc[page_idx]
        
        # Native text extraction
        page_text = page.get_text("text").strip()
        ocr_applied = False
        
        # OCR fallback for scanned diagrams / image-based pages
        if len(page_text) < 40:
            try:
                ocr_tp = page.get_textpage_ocr(language='eng')
                ocr_result = page.get_text("text", textpage=ocr_tp).strip()
                if len(ocr_result) > 20:
                    page_text = ocr_result
                    ocr_applied = True
                    ocr_pages_count += 1
            except Exception:
                pass
        
        if not page_text:
            continue
            
        detected_sec = detect_section_header(page_text)
        if detected_sec and detected_sec != "General Architecture Specification":
            current_section = detected_sec
            
        page_chunks = text_splitter.split_text(page_text)
        for chunk_idx, chunk in enumerate(page_chunks):
            doc_chunk = Document(
                page_content=chunk,
                metadata={
                    "source": original_filename,
                    "project_id": project_id,
                    "page": page_num,
                    "section": current_section,
                    "chunk_index": chunk_idx,
                    "ocr": ocr_applied
                }
            )
            all_chunks.append(doc_chunk)
            
    if all_chunks:
        collection_name = get_project_collection_name(project_id)
        Chroma.from_documents(
            documents=all_chunks,
            embedding=embeddings,
            persist_directory=settings.CHROMA_PERSIST_DIR,
            collection_name=collection_name
        )
        
    return page_count, len(all_chunks), ocr_pages_count
