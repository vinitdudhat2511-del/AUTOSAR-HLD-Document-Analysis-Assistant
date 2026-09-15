from sqlalchemy import create_engine, Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

from app.config import settings

DATABASE_URL = settings.DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="engineer", nullable=False)  # admin, architect, engineer
    token = Column(String, unique=True, index=True, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    allowed_projects = Column(String, default="*")  # Comma-separated project IDs or *
    created_at = Column(DateTime, default=datetime.utcnow)

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    doc_id = Column(String, unique=True, index=True)
    filename = Column(String, index=True)
    stored_path = Column(String)
    project_id = Column(String, index=True, nullable=False)
    uploaded_by = Column(String, nullable=False)
    upload_time = Column(DateTime, default=datetime.utcnow)
    version = Column(String, default="1.0")
    status = Column(String, default="processed")
    page_count = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)

# --- Architecture Knowledge Base Models (Structured Extraction) ---

class ArchitectureComponent(Base):
    __tablename__ = "architecture_components"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(String, index=True, nullable=False)
    doc_id = Column(String, index=True)
    name = Column(String, index=True, nullable=False)
    component_type = Column(String, default="Application SWC")  # Application, SensorActuator, Service, CDD, BSW Module
    layer = Column(String, default="Application")              # Application, RTE, Services, ECU Abstraction, MCAL, CDD
    description = Column(Text, default="")
    source_page = Column(Integer, default=1)
    extracted_at = Column(DateTime, default=datetime.utcnow)

class ArchitectureInterface(Base):
    __tablename__ = "architecture_interfaces"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(String, index=True, nullable=False)
    doc_id = Column(String, index=True)
    name = Column(String, index=True, nullable=False)
    interface_type = Column(String, default="Sender-Receiver")  # Sender-Receiver, Client-Server, Parameter, Mode Switch
    elements_or_operations = Column(Text, default="")
    source_page = Column(Integer, default=1)
    extracted_at = Column(DateTime, default=datetime.utcnow)

class ArchitecturePort(Base):
    __tablename__ = "architecture_ports"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(String, index=True, nullable=False)
    doc_id = Column(String, index=True)
    component_name = Column(String, index=True, nullable=False)
    port_name = Column(String, nullable=False)
    port_type = Column(String, default="PPort")  # PPort (Provided), RPort (Required), PRPort
    interface_name = Column(String, default="")
    source_page = Column(Integer, default=1)

class ArchitectureDependency(Base):
    __tablename__ = "architecture_dependencies"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(String, index=True, nullable=False)
    doc_id = Column(String, index=True)
    source_component = Column(String, index=True, nullable=False)
    target_component = Column(String, index=True, nullable=False)
    interface_name = Column(String, default="")
    connector_type = Column(String, default="Assembly")  # Assembly, Delegation
    status = Column(String, default="Connected")        # Connected, Missing Target, Unresolved

# --- Audit Logging & Governance Models ---

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    username = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)
    action = Column(String, index=True, nullable=False)  # UPLOAD, QUERY, EXTRACT, COMPARE, EXPORT, REVIEW_DISPOSITION
    project_id = Column(String, index=True, nullable=False)
    doc_id = Column(String, nullable=True)
    query_text = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    citations_count = Column(Integer, default=0)
    review_status = Column(String, default="PENDING_REVIEW")  # PENDING_REVIEW, ACCEPTED, MODIFIED, REJECTED
    disposition_notes = Column(Text, nullable=True)
    disposed_by = Column(String, nullable=True)
    disposed_at = Column(DateTime, nullable=True)

def init_db():
    Base.metadata.create_all(bind=engine)
    # Ensure all required columns exist in SQLite documents table
    with engine.connect() as conn:
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(documents)")
        cols = [row[1] for row in cursor.fetchall()]
        if cols:
            if "version" not in cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN version VARCHAR DEFAULT '1.0'")
            if "page_count" not in cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN page_count INTEGER DEFAULT 0")
            if "chunk_count" not in cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN chunk_count INTEGER DEFAULT 0")
            if "doc_id" not in cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN doc_id VARCHAR")
            if "stored_path" not in cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN stored_path VARCHAR")
            if "project_id" not in cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN project_id VARCHAR DEFAULT 'AUTOSAR_Classic_BSW'")
            if "uploaded_by" not in cols:
                cursor.execute("ALTER TABLE documents ADD COLUMN uploaded_by VARCHAR DEFAULT 'admin'")
            conn.connection.commit()
        # Migrate architecture_ports: add doc_id if missing
        cursor = conn.connection.cursor()
        cursor.execute("PRAGMA table_info(architecture_ports)")
        port_cols = [row[1] for row in cursor.fetchall()]
        if port_cols and "doc_id" not in port_cols:
            cursor.execute("ALTER TABLE architecture_ports ADD COLUMN doc_id VARCHAR")
            conn.connection.commit()
        # Migrate architecture_dependencies: add doc_id if missing
        cursor.execute("PRAGMA table_info(architecture_dependencies)")
        dep_cols = [row[1] for row in cursor.fetchall()]
        if dep_cols and "doc_id" not in dep_cols:
            cursor.execute("ALTER TABLE architecture_dependencies ADD COLUMN doc_id VARCHAR")
            conn.connection.commit()
        # Migrate users: add token_expires_at if missing
        cursor.execute("PRAGMA table_info(users)")
        user_cols = [row[1] for row in cursor.fetchall()]
        if user_cols and "token_expires_at" not in user_cols:
            cursor.execute("ALTER TABLE users ADD COLUMN token_expires_at DATETIME")
            conn.connection.commit()
        # Security hardening: invalidate any previously seeded static backdoor tokens
        cursor.execute("UPDATE users SET token = NULL, token_expires_at = NULL WHERE token LIKE 'demo-token-%'")
        # Clean up legacy orphaned documents and extraction rows left over from prior uploads
        cursor.execute("DELETE FROM documents WHERE doc_id IS NULL")
        cursor.execute("SELECT doc_id FROM documents WHERE doc_id IS NOT NULL")
        valid_doc_ids = [row[0] for row in cursor.fetchall()]
        if valid_doc_ids:
            placeholders = ",".join(["?"] * len(valid_doc_ids))
            cursor.execute(f"DELETE FROM architecture_components WHERE doc_id IS NULL OR doc_id NOT IN ({placeholders})", valid_doc_ids)
            cursor.execute(f"DELETE FROM architecture_interfaces WHERE doc_id IS NULL OR doc_id NOT IN ({placeholders})", valid_doc_ids)
            cursor.execute(f"DELETE FROM architecture_ports WHERE doc_id IS NULL OR doc_id NOT IN ({placeholders})", valid_doc_ids)
            cursor.execute(f"DELETE FROM architecture_dependencies WHERE doc_id IS NULL OR doc_id NOT IN ({placeholders})", valid_doc_ids)
        conn.connection.commit()
    if settings.SEED_DEMO_DATA:
        seed_initial_data()

def seed_initial_data():
    from app.auth import hash_password
    db = SessionLocal()
    try:
        # Seed Projects
        default_projects = [
            ("AUTOSAR_Adaptive", "AUTOSAR Adaptive Platform", "Adaptive core services, execution management, diagnostics"),
            ("AUTOSAR_Classic_BSW", "AUTOSAR Classic BSW", "Basic Software modules (MCAL, ECUM, Com stack, OS, RTE)"),
            ("Powertrain_Gateway", "Powertrain Gateway ECU", "High-speed CAN/Ethernet routing & gateway logic")
        ]
        for pid, name, desc in default_projects:
            if not db.query(Project).filter(Project.id == pid).first():
                db.add(Project(id=pid, name=name, description=desc))
        
        # Seed Default Users using configurable credentials
        # Note: Tokens are NEVER pre-seeded statically. Users must authenticate via /api/v1/auth/login.
        default_users = [
            ("admin", settings.DEFAULT_ADMIN_PASSWORD, "admin", "*"),
            ("architect_john", settings.DEFAULT_ARCHITECT_PASSWORD, "architect", "AUTOSAR_Adaptive,AUTOSAR_Classic_BSW,Powertrain_Gateway"),
            ("engineer_alice", settings.DEFAULT_ENGINEER_PASSWORD, "engineer", "AUTOSAR_Adaptive,AUTOSAR_Classic_BSW"),
        ]
        for uname, pwd, role, prjs in default_users:
            user = db.query(User).filter(User.username == uname).first()
            if not user:
                new_user = User(
                    username=uname,
                    hashed_password=hash_password(pwd),
                    role=role,
                    token=None,
                    token_expires_at=None,
                    allowed_projects=prjs
                )
                db.add(new_user)
        db.commit()
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
