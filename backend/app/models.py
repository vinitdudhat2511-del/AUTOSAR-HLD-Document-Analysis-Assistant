from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

# --- Auth Models ---

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    username: str
    role: str
    allowed_projects: List[str]

class UserProfile(BaseModel):
    username: str
    role: str
    allowed_projects: List[str]

class ProjectItem(BaseModel):
    id: str
    name: str
    description: str

# --- RAG & Citations Models ---

class Citation(BaseModel):
    source: str
    page: int
    section: Optional[str] = "General"
    snippet: str

class QueryRequest(BaseModel):
    query: str
    project_id: str

class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence_score: float
    confidence_level: str  # HIGH, MEDIUM, LOW
    limitations: List[str]
    review_status: str     # PENDING_REVIEW, ACCEPTED, MODIFIED, REJECTED
    audit_id: Optional[int] = None
    project_id: str

# --- Ingestion Models ---

class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    project_id: str
    version: str
    page_count: int
    chunks_created: int
    ocr_pages_detected: int
    message: str

# --- Structured Extraction Models ---

class ComponentItem(BaseModel):
    name: str
    component_type: str
    layer: str
    description: str
    source_page: int

class InterfaceItem(BaseModel):
    name: str
    interface_type: str
    elements_or_operations: str
    source_page: int

class PortItem(BaseModel):
    component_name: str
    port_name: str
    port_type: str
    interface_name: str
    source_page: int

class DependencyItem(BaseModel):
    source_component: str
    target_component: str
    interface_name: str
    connector_type: str
    status: str

class ArchitectureInventoryResponse(BaseModel):
    project_id: str
    total_components: int
    total_interfaces: int
    total_ports: int
    total_dependencies: int
    components: List[ComponentItem]
    interfaces: List[InterfaceItem]
    ports: List[PortItem]
    dependencies: List[DependencyItem]
    inconsistencies: List[str]

# --- Document Comparison / Revision Diffing Models ---

class CompareRequest(BaseModel):
    project_id: str
    doc_id_base: Optional[str] = None
    doc_id_target: Optional[str] = None

class InconsistencyItem(BaseModel):
    category: str
    severity: str  # WARNING, ERROR, INFO
    component_or_interface: str
    description: str
    recommendation: str

class ComparisonReport(BaseModel):
    project_id: str
    base_document: str
    target_document: str
    added_components: List[str]
    removed_components: List[str]
    modified_interfaces: List[str]
    unconnected_ports: List[str]
    inconsistencies: List[InconsistencyItem]
    summary: str

# --- Audit & Governance Models ---

class AuditLogItem(BaseModel):
    id: int
    timestamp: datetime
    username: str
    role: str
    action: str
    project_id: str
    query_text: Optional[str] = None
    confidence_score: Optional[float] = None
    review_status: str
    disposition_notes: Optional[str] = None
    disposed_by: Optional[str] = None

class DispositionRequest(BaseModel):
    audit_id: int
    disposition: str  # ACCEPTED, MODIFIED, REJECTED
    notes: Optional[str] = ""

class DispositionResponse(BaseModel):
    audit_id: int
    status: str
    message: str
