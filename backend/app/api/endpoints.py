import os
import re
import uuid
from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, status, Response, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime

from app.models import (
    QueryRequest, QueryResponse, UploadResponse,
    LoginRequest, LoginResponse, UserProfile, ProjectItem,
    ArchitectureInventoryResponse, CompareRequest, ComparisonReport,
    AuditLogItem, DispositionRequest, DispositionResponse
)
from app.database import get_db, Document, Project, User, AuditLog
from app.auth import (
    get_current_user, RequireRole, check_project_access,
    verify_password, generate_session_token
)
from app.config import settings
from app.services.ingestion import process_and_store_document, remove_existing_document_chunks
from app.services.rag import query_documents
from app.services.extractor import extract_architecture_from_document, get_project_inventory
from app.services.comparator import compare_documents_or_revisions
from app.services.exporter import (
    export_project_findings_json, export_components_csv, export_engineering_report_markdown
)

router = APIRouter()
UPLOAD_DIR = os.path.abspath(settings.UPLOAD_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)

def process_document_background(
    file_path: str,
    project_id: str,
    clean_name: str,
    version: str,
    doc_id: str,
    username: str,
    user_role: str,
    old_doc_id: str = None
):
    """Background task for document ingestion and architecture extraction."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        # Ingestion into ChromaDB with OCR fallback and chunk deduplication
        page_count, num_chunks, ocr_pages = process_and_store_document(
            file_path=file_path,
            project_id=project_id,
            original_filename=clean_name
        )
        
        # Update Document record
        doc = db.query(Document).filter(Document.doc_id == doc_id).first()
        if doc:
            doc.status = "processed"
            doc.page_count = page_count
            doc.chunk_count = num_chunks
        
        # Automatic Structured Architecture Extraction
        extract_stats = extract_architecture_from_document(
            file_path=file_path,
            project_id=project_id,
            doc_id=doc_id,
            db=db,
            old_doc_id=old_doc_id
        )
        
        # Record into Governance Audit Log
        audit = AuditLog(
            username=username,
            role=user_role,
            action="UPLOAD",
            project_id=project_id,
            doc_id=doc_id,
            response_summary=(
                f"Ingested '{clean_name}' (v{version}): {page_count} pages, {num_chunks} chunks, "
                f"{ocr_pages} OCR pages. Extracted {extract_stats['components_extracted']} SWCs."
            ),
            review_status="ACCEPTED"
        )
        db.add(audit)
        db.commit()
    except Exception as e:
        doc = db.query(Document).filter(Document.doc_id == doc_id).first()
        if doc:
            doc.status = f"error: {str(e)}"
            db.commit()
    finally:
        db.close()

from datetime import datetime, timedelta

# --- Authentication Endpoints ---

@router.post("/auth/login", response_model=LoginResponse)
async def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    # Always issue a fresh, time-limited session token
    user.token = generate_session_token()
    user.token_expires_at = datetime.utcnow() + timedelta(hours=settings.SESSION_TOKEN_EXPIRE_HOURS)
    db.commit()
    db.refresh(user)
    
    allowed = [p.strip() for p in (user.allowed_projects or "").split(",") if p.strip()]
    return LoginResponse(
        token=user.token,
        username=user.username,
        role=user.role,
        allowed_projects=allowed
    )

@router.post("/auth/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Server-side session termination and token revocation."""
    current_user.token = None
    current_user.token_expires_at = None
    db.commit()
    return {"message": "Session terminated successfully"}

@router.get("/auth/me", response_model=UserProfile)
async def get_profile(current_user: User = Depends(get_current_user)):
    allowed = [p.strip() for p in (current_user.allowed_projects or "").split(",") if p.strip()]
    return UserProfile(
        username=current_user.username,
        role=current_user.role,
        allowed_projects=allowed
    )

# --- Project Management Endpoints ---

@router.get("/projects", response_model=List[ProjectItem])
async def list_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    all_projects = db.query(Project).all()
    if current_user.role == "admin" or current_user.allowed_projects == "*":
        return [ProjectItem(id=p.id, name=p.name, description=p.description) for p in all_projects]
    
    allowed_ids = [p.strip() for p in (current_user.allowed_projects or "").split(",") if p.strip()]
    return [
        ProjectItem(id=p.id, name=p.name, description=p.description)
        for p in all_projects if p.id in allowed_ids
    ]

# --- Document Ingestion & Status Tracking ---

@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: str = Form(...),
    version: str = Form("1.0"),
    current_user: User = Depends(RequireRole(["admin", "architect"])),
    db: Session = Depends(get_db)
):
    """
    Asynchronous Document Ingestion:
    - Path traversal sanitization & UUID naming
    - Re-upload deduplication (removes old chunks if file exists)
    - Offloads CPU-intensive PDF parsing & embedding to background task
    """
    if not check_project_access(current_user, project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{current_user.username}' is not authorized to upload to project '{project_id}'"
        )
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    raw_name = file.filename or "document.pdf"
    base_name = os.path.basename(raw_name)
    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', base_name)
    
    if not clean_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF documents are supported.")
    
    doc_id = str(uuid.uuid4())
    safe_filename = f"{doc_id}_{clean_name}"
    target_path = os.path.abspath(os.path.join(UPLOAD_DIR, safe_filename))
    
    if not target_path.startswith(UPLOAD_DIR):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Security violation: Path traversal detected in filename."
        )
    
    # Check for existing document with same filename in project (Deduplication)
    existing_doc = db.query(Document).filter(
        Document.project_id == project_id,
        Document.filename == clean_name
    ).first()
    
    old_doc_id = None
    if existing_doc:
        # Capture old doc_id so we can clean up its extraction rows later
        old_doc_id = existing_doc.doc_id
        # Clean up old file on disk if it exists
        if existing_doc.stored_path and os.path.exists(existing_doc.stored_path):
            try:
                os.remove(existing_doc.stored_path)
            except Exception:
                pass
        # Mark as updating
        existing_doc.doc_id = doc_id
        existing_doc.stored_path = target_path
        existing_doc.version = version
        existing_doc.status = "processing"
        existing_doc.uploaded_by = current_user.username
        existing_doc.upload_time = datetime.utcnow()
        db_doc = existing_doc
    else:
        db_doc = Document(
            doc_id=doc_id,
            filename=clean_name,
            stored_path=target_path,
            project_id=project_id,
            uploaded_by=current_user.username,
            version=version,
            status="processing",
            page_count=0,
            chunk_count=0
        )
        db.add(db_doc)

    # Save uploaded file to disk
    size = 0
    try:
        with open(target_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.MAX_FILE_SIZE:
                    buffer.close()
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE // (1024 * 1024)}MB"
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(target_path):
            os.remove(target_path)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    db.commit()
    db.refresh(db_doc)

    # Dispatch to Background Task
    background_tasks.add_task(
        process_document_background,
        file_path=target_path,
        project_id=project_id,
        clean_name=clean_name,
        version=version,
        doc_id=doc_id,
        username=current_user.username,
        user_role=current_user.role,
        old_doc_id=old_doc_id
    )

    return UploadResponse(
        doc_id=doc_id,
        filename=clean_name,
        project_id=project_id,
        version=version,
        page_count=0,
        chunks_created=0,
        ocr_pages_detected=0,
        message=f"Document '{clean_name}' upload accepted. Processing and architecture extraction running in background."
    )

@router.get("/documents/{doc_id}/status")
async def get_document_status(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Check asynchronous document ingestion status."""
    doc = db.query(Document).filter(Document.doc_id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not check_project_access(current_user, doc.project_id):
        raise HTTPException(status_code=403, detail="Project access denied")
        
    return {
        "doc_id": doc.doc_id,
        "filename": doc.filename,
        "project_id": doc.project_id,
        "version": doc.version,
        "status": doc.status,
        "page_count": doc.page_count,
        "chunk_count": doc.chunk_count,
        "uploaded_by": doc.uploaded_by,
        "upload_time": doc.upload_time
    }

@router.get("/documents")
async def list_documents(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all ingested documents for a project."""
    if not check_project_access(current_user, project_id):
        raise HTTPException(status_code=403, detail="Project access denied")
    docs = db.query(Document).filter(
        Document.project_id == project_id
    ).order_by(Document.upload_time.desc()).all()
    return [
        {
            "doc_id": d.doc_id,
            "filename": d.filename,
            "version": d.version,
            "status": d.status,
            "page_count": d.page_count,
            "chunk_count": d.chunk_count,
            "uploaded_by": d.uploaded_by,
            "upload_time": str(d.upload_time)
        }
        for d in docs
    ]

# --- Architecture Search & Q&A ---

@router.post("/query", response_model=QueryResponse)
async def query_knowledge_base(
    request: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not check_project_access(current_user, request.project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User '{current_user.username}' does not have access to project '{request.project_id}'"
        )
    try:
        return query_documents(
            query_text=request.query,
            project_id=request.project_id,
            user=current_user,
            db=db
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")

# --- Structured Inventory, Comparison, Export, and Audit Endpoints ---

@router.get("/architecture/inventory", response_model=ArchitectureInventoryResponse)
async def get_inventory(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not check_project_access(current_user, project_id):
        raise HTTPException(status_code=403, detail="Project access denied")
    return get_project_inventory(project_id, db)

@router.post("/architecture/compare", response_model=ComparisonReport)
async def compare_architecture(
    request: CompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not check_project_access(current_user, request.project_id):
        raise HTTPException(status_code=403, detail="Project access denied")
    report = compare_documents_or_revisions(
        project_id=request.project_id,
        doc_id_base=request.doc_id_base,
        doc_id_target=request.doc_id_target,
        db=db
    )
    audit = AuditLog(
        username=current_user.username,
        role=current_user.role,
        action="COMPARE",
        project_id=request.project_id,
        response_summary=report.summary,
        review_status="ACCEPTED"
    )
    db.add(audit)
    db.commit()
    return report

@router.get("/architecture/export")
async def export_findings(
    project_id: str,
    format: str = "json",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not check_project_access(current_user, project_id):
        raise HTTPException(status_code=403, detail="Project access denied")
    fmt = format.lower().strip()
    if fmt == "csv":
        csv_content = export_components_csv(project_id, db)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=architecture_inventory_{project_id}.csv"}
        )
    elif fmt in ["markdown", "md"]:
        md_content = export_engineering_report_markdown(project_id, db)
        return Response(
            content=md_content,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=architecture_report_{project_id}.md"}
        )
    else:
        json_content = export_project_findings_json(project_id, db)
        return Response(
            content=json_content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=architecture_findings_{project_id}.json"}
        )

@router.get("/audit/logs", response_model=List[AuditLogItem])
async def list_audit_logs(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not check_project_access(current_user, project_id):
        raise HTTPException(status_code=403, detail="Project access denied")
    logs = db.query(AuditLog).filter(
        AuditLog.project_id == project_id
    ).order_by(AuditLog.timestamp.desc()).limit(100).all()
    return [
        AuditLogItem(
            id=log.id,
            timestamp=log.timestamp,
            username=log.username,
            role=log.role,
            action=log.action,
            project_id=log.project_id,
            query_text=log.query_text,
            confidence_score=log.confidence_score,
            review_status=log.review_status,
            disposition_notes=log.disposition_notes,
            disposed_by=log.disposed_by
        ) for log in logs
    ]

@router.post("/audit/disposition", response_model=DispositionResponse)
async def update_disposition(
    request: DispositionRequest,
    current_user: User = Depends(RequireRole(["admin", "architect"])),
    db: Session = Depends(get_db)
):
    log = db.query(AuditLog).filter(AuditLog.id == request.audit_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Audit log entry not found")
    log.review_status = request.disposition
    log.disposition_notes = request.notes
    log.disposed_by = current_user.username
    log.disposed_at = datetime.utcnow()
    db.commit()
    return DispositionResponse(
        audit_id=log.id,
        status=request.disposition,
        message=f"Output disposition successfully updated to '{request.disposition}' by {current_user.username}."
    )
