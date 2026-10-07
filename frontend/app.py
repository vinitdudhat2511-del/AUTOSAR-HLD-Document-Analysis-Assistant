import streamlit as st
import requests
import os
import json
import time
import pandas as pd

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api/v1")
HEALTH_URL = API_BASE_URL.replace("/api/v1", "/health")

st.set_page_config(
    page_title="AUTOSAR HLD Engineering Assistant",
    page_icon="🚘",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .reportview-container { background: #0e1117; }
    .main .block-container { padding-top: 1.5rem; max-width: 95%; }
    h1, h2, h3 { color: #4da6ff; font-family: 'Inter', sans-serif; font-weight: 700; }
    
    .badge-role {
        display: inline-block; padding: 3px 10px; border-radius: 12px;
        font-size: 0.78rem; font-weight: 700; text-transform: uppercase; margin-left: 6px;
    }
    .badge-admin { background-color: #d32f2f; color: white; }
    .badge-architect { background-color: #2e7d32; color: white; }
    .badge-engineer { background-color: #0288d1; color: white; }
    
    .status-badge {
        padding: 6px 12px; border-radius: 6px; font-size: 0.82rem; font-weight: 600; margin-bottom: 12px;
    }
    .status-online { background-color: #1b4721; color: #7ee787; border: 1px solid #238636; }
    .status-offline { background-color: #4c1d24; color: #ffa198; border: 1px solid #da3633; }
    
    .metric-card {
        background-color: #161b22; border: 1px solid #30363d; border-radius: 8px;
        padding: 14px; text-align: center;
    }
    .metric-val { font-size: 1.8rem; font-weight: 700; color: #58a6ff; }
    .metric-lbl { font-size: 0.85rem; color: #8b949e; text-transform: uppercase; }
    
    .citation-card {
        background-color: #161b22; border-left: 4px solid #58a6ff; border-radius: 6px;
        padding: 10px 14px; margin-top: 8px; margin-bottom: 8px; font-size: 0.88rem;
    }
    .citation-header { font-weight: 700; color: #79c0ff; margin-bottom: 4px; }
    .citation-snippet { color: #c9d1d9; font-style: italic; font-size: 0.82rem; }
    
    .conf-high { color: #3fb950; font-weight: 700; }
    .conf-med { color: #d29922; font-weight: 700; }
    .conf-low { color: #f85149; font-weight: 700; }
    
    .limitation-box {
        background-color: #21262d; border: 1px solid #30363d; border-radius: 6px;
        padding: 10px; margin-top: 8px; font-size: 0.82rem; color: #8b949e;
    }
</style>
""", unsafe_allow_html=True)

# Session State Initialization
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "user_info" not in st.session_state:
    st.session_state.user_info = None
if "active_project" not in st.session_state:
    st.session_state.active_project = None
if "messages" not in st.session_state:
    st.session_state.messages = []

def check_backend_health():
    """Live check against backend /health endpoint with host fallback and resilient timeout."""
    try:
        r = requests.get(HEALTH_URL, timeout=5)
        if r.status_code == 200:
            info = r.json()
            return True, f"Online (v{info.get('version', '1.0')} | {info.get('llm_model', 'llama3')})"
    except Exception:
        pass
    
    # Try alternate hostname (localhost <-> 127.0.0.1)
    try:
        alt_url = HEALTH_URL.replace("127.0.0.1", "localhost") if "127.0.0.1" in HEALTH_URL else HEALTH_URL.replace("localhost", "127.0.0.1")
        r = requests.get(alt_url, timeout=5)
        if r.status_code == 200:
            info = r.json()
            return True, f"Online (v{info.get('version', '1.0')} | {info.get('llm_model', 'llama3')})"
    except Exception:
        pass
        
    return False, "Offline"

def get_auth_headers():
    if st.session_state.auth_token:
        return {"Authorization": f"Bearer {st.session_state.auth_token}"}
    return {}

def login(username, password):
    try:
        res = requests.post(
            f"{API_BASE_URL}/auth/login",
            json={"username": username, "password": password},
            timeout=10
        )
        if res.status_code == 200:
            data = res.json()
            st.session_state.auth_token = data["token"]
            st.session_state.user_info = {
                "username": data["username"],
                "role": data["role"],
                "allowed_projects": data["allowed_projects"]
            }
            st.session_state.messages = []
            st.rerun()
        else:
            st.error(f"Login failed: {res.json().get('detail', 'Invalid credentials')}")
    except Exception as e:
        st.error(f"Cannot connect to auth service: {str(e)}")

def logout():
    if st.session_state.auth_token:
        try:
            requests.post(f"{API_BASE_URL}/auth/logout", headers=get_auth_headers(), timeout=5)
        except Exception:
            pass
    st.session_state.auth_token = None
    st.session_state.user_info = None
    st.session_state.active_project = None
    st.session_state.messages = []
    st.rerun()

def fetch_projects():
    try:
        res = requests.get(f"{API_BASE_URL}/projects", headers=get_auth_headers(), timeout=10)
        if res.status_code == 200:
            return res.json()
        return []
    except Exception:
        return []

def upload_document_async(file, project_id, version="1.0"):
    headers = get_auth_headers()
    files = {"file": (file.name, file, "application/pdf")}
    data = {"project_id": project_id, "version": version}
    
    with st.spinner("Uploading and scheduling background ingestion..."):
        try:
            res = requests.post(f"{API_BASE_URL}/upload", headers=headers, files=files, data=data, timeout=30)
            if res.status_code != 200:
                st.sidebar.error(f"❌ Upload rejected: {res.json().get('detail')}")
                return
            
            upload_data = res.json()
            doc_id = upload_data["doc_id"]
            st.sidebar.info(f"⏳ Ingestion started for doc #{doc_id[:8]}. Running background OCR & extraction...")
        except Exception as e:
            st.sidebar.error(f"❌ Network error: {str(e)}")
            return

    # Poll status in background with UI progress bar
    progress_bar = st.sidebar.progress(10)
    status_text = st.sidebar.empty()
    
    max_retries = 60
    for i in range(max_retries):
        time.sleep(2)
        progress = min(90, 10 + i * 4)
        progress_bar.progress(progress)
        status_text.caption(f"Processing pages & extracting architecture... ({i * 2}s)")
        try:
            status_res = requests.get(f"{API_BASE_URL}/documents/{doc_id}/status", headers=headers, timeout=10)
            if status_res.status_code == 200:
                doc_stat = status_res.json()
                if doc_stat["status"] == "processed":
                    progress_bar.progress(100)
                    status_text.empty()
                    st.sidebar.success(f"✅ Ingestion complete! Pages: {doc_stat.get('page_count')}, Chunks: {doc_stat.get('chunk_count')}")
                    time.sleep(1)
                    st.rerun()
                    return
                elif "error" in doc_stat["status"]:
                    progress_bar.empty()
                    status_text.empty()
                    st.sidebar.error(f"❌ Ingestion failed: {doc_stat['status']}")
                    return
        except Exception:
            pass

def query_assistant(query, project_id):
    headers = get_auth_headers()
    payload = {"query": query, "project_id": project_id}
    try:
        res = requests.post(f"{API_BASE_URL}/query", headers=headers, json=payload, timeout=60)
        if res.status_code == 200:
            return res.json()
        else:
            st.error(f"Query Error ({res.status_code}): {res.json().get('detail', 'Error')}")
            return None
    except Exception as e:
        st.error(f"Connection error: {str(e)}")
        return None

def fetch_inventory(project_id):
    try:
        res = requests.get(f"{API_BASE_URL}/architecture/inventory?project_id={project_id}", headers=get_auth_headers(), timeout=15)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None

def fetch_documents(project_id):
    try:
        res = requests.get(f"{API_BASE_URL}/documents?project_id={project_id}", headers=get_auth_headers(), timeout=10)
        if res.status_code == 200:
            return res.json()
        return []
    except Exception:
        return []

def fetch_comparison(project_id, doc_id_base=None, doc_id_target=None):
    try:
        payload = {"project_id": project_id}
        if doc_id_base:
            payload["doc_id_base"] = doc_id_base
        if doc_id_target:
            payload["doc_id_target"] = doc_id_target
        res = requests.post(f"{API_BASE_URL}/architecture/compare", headers=get_auth_headers(), json=payload, timeout=25)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception:
        return None

def fetch_audit_logs(project_id):
    try:
        res = requests.get(f"{API_BASE_URL}/audit/logs?project_id={project_id}", headers=get_auth_headers(), timeout=15)
        if res.status_code == 200:
            return res.json()
        return []
    except Exception:
        return []

def submit_disposition(audit_id, disposition, notes=""):
    try:
        res = requests.post(
            f"{API_BASE_URL}/audit/disposition",
            headers=get_auth_headers(),
            json={"audit_id": audit_id, "disposition": disposition, "notes": notes},
            timeout=10
        )
        return res.status_code == 200
    except Exception:
        return False

# --- Live Health Status Badge (Sidebar) ---
with st.sidebar:
    is_live, health_msg = check_backend_health()
    if is_live:
        st.markdown(f"<div class='status-badge status-online'>🟢 Backend API: {health_msg}</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='status-badge status-offline'>🔴 Backend API: {health_msg}</div>", unsafe_allow_html=True)

# --- Authentication Screen ---
if not st.session_state.auth_token or not st.session_state.user_info:
    st.title("🚘 AUTOSAR HLD Document Analysis Assistant")
    st.markdown("### Enterprise Architecture Knowledge & Safety Intelligence Platform")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("#### Sign In")
        with st.form("login_form"):
            username = st.text_input("Engineering ID / Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Authenticate", type="primary", use_container_width=True)
            if submit:
                if username and password:
                    login(username, password)
                else:
                    st.warning("Please enter credentials.")
                    
    with col2:
        with st.expander("🔑 Role-Based Access Control Demo Accounts", expanded=True):
            st.markdown("""
            > ⚠️ **Security Advisory**: Demo accounts are intended solely for local sandbox testing. In production, configure unique credentials in environment variables and set `SEED_DEMO_DATA=false`.

            | Username | Password | Role | Program Scope & Permissions |
            | :--- | :--- | :--- | :--- |
            | `admin` | `Admin@123` | **Admin** | Full system access, all programs, upload & review |
            | `architect_john` | `Arch@123` | **Architect** | Ingest HLDs, extract SWCs, run diffs, review outputs |
            | `engineer_alice` | `Eng@123` | **Engineer** | **Read-only query** & export (upload blocked) |
            """)
    st.stop()

# --- Authenticated Shell ---
user = st.session_state.user_info
role = user["role"]

with st.sidebar:
    st.markdown(f"### 👤 {user['username']} <span class='badge-role badge-{role}'>{role}</span>", unsafe_allow_html=True)
    if st.button("Sign Out", use_container_width=True):
        logout()
        
    st.markdown("---")
    st.subheader("📁 Program Workspace")
    projects = fetch_projects()
    if not projects:
        st.warning("No authorized programs assigned.")
        st.stop()
        
    proj_map = {p["id"]: f"{p['name']} ({p['id']})" for p in projects}
    active_pid = st.selectbox("Select Active ECU Program", options=list(proj_map.keys()), format_func=lambda x: proj_map[x])
    st.session_state.active_project = active_pid
    
    selected_p = next((p for p in projects if p["id"] == active_pid), None)
    if selected_p:
        st.caption(f"📌 {selected_p.get('description')}")
        
    st.markdown("---")
    st.subheader("📄 Document Ingestion")
    if role in ["admin", "architect"]:
        doc_version = st.text_input("Document Version", value="1.0")
        uploaded_file = st.file_uploader("Upload AUTOSAR HLD (PDF)", type=["pdf"], help="Sanitized, deduplicated, and processed in background with OCR fallback.")
        if uploaded_file and st.button("Ingest & Process (Background Task)", type="primary", use_container_width=True):
            upload_document_async(uploaded_file, active_pid, doc_version)
    else:
        st.info("🔒 **Read-Only Access**: `engineer` role has query and export permissions. Document upload requires `architect` or `admin` authorization.")

active_proj = st.session_state.active_project
st.title(f"🚘 AUTOSAR HLD Assistant: `{active_proj}`")
st.caption("AI-assisted architectural knowledge extraction, grounded Q&A, dependency mapping, and governance compliance.")

# Main Navigation Tabs
tab_qa, tab_inv, tab_diff, tab_export, tab_audit = st.tabs([
    "💬 Architecture Q&A",
    "🧩 Component & Dependency Inventory",
    "🔍 Revision Comparison & Inconsistencies",
    "📤 Structured Export",
    "🛡️ Governance Audit Trail"
])

# --- TAB 1: ARCHITECTURE Q&A ---
with tab_qa:
    col_l, col_r = st.columns([3, 1])
    with col_l:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                
                # Render Citations
                if msg.get("citations"):
                    st.markdown("**📄 Grounded Document Citations:**")
                    for cit in msg["citations"]:
                        st.markdown(f"""
                        <div class="citation-card">
                            <div class="citation-header">📘 {cit['source']} — Page {cit['page']} (Section: {cit.get('section', 'General')})</div>
                            <div class="citation-snippet">"{cit['snippet']}"</div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                # Render Confidence & Limitations
                if "confidence_score" in msg:
                    score = msg["confidence_score"]
                    level = msg.get("confidence_level", "MEDIUM")
                    color_cls = "conf-high" if level == "HIGH" else ("conf-med" if level == "MEDIUM" else "conf-low")
                    st.markdown(f"**Confidence Indicator:** <span class='{color_cls}'>{level} ({int(score * 100)}%)</span> <span style='font-size:0.75rem; color:#8b949e;'>(Retrieval Heuristic)</span> | Review Status: `{msg.get('review_status', 'PENDING_REVIEW')}`", unsafe_allow_html=True)
                    
                if msg.get("limitations"):
                    st.markdown("<div class='limitation-box'><b>⚠️ Architectural Boundaries & Limitations:</b><br>" + "<br>• ".join([""] + msg["limitations"]) + "</div>", unsafe_allow_html=True)

        if prompt := st.chat_input("Ask an architectural question about SWCs, RTE, BSW, MCAL, or interfaces..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
                
            with st.chat_message("assistant"):
                with st.spinner("Analyzing architecture with grounded page retrieval..."):
                    res = query_assistant(prompt, active_proj)
                    if res:
                        st.markdown(res["answer"])
                        if res.get("citations"):
                            st.markdown("**📄 Grounded Document Citations:**")
                            for cit in res["citations"]:
                                st.markdown(f"""
                                <div class="citation-card">
                                    <div class="citation-header">📘 {cit['source']} — Page {cit['page']} (Section: {cit.get('section', 'General')})</div>
                                    <div class="citation-snippet">"{cit['snippet']}"</div>
                                </div>
                                """, unsafe_allow_html=True)
                                
                        score = res.get("confidence_score", 0.0)
                        level = res.get("confidence_level", "MEDIUM")
                        color_cls = "conf-high" if level == "HIGH" else ("conf-med" if level == "MEDIUM" else "conf-low")
                        st.markdown(f"**Confidence Indicator:** <span class='{color_cls}'>{level} ({int(score * 100)}%)</span> <span style='font-size:0.75rem; color:#8b949e;'>(Retrieval Heuristic)</span> | Review Status: `{res.get('review_status', 'PENDING_REVIEW')}`", unsafe_allow_html=True)
                        
                        if res.get("limitations"):
                            st.markdown("<div class='limitation-box'><b>⚠️ Architectural Boundaries & Limitations:</b><br>" + "<br>• ".join([""] + res["limitations"]) + "</div>", unsafe_allow_html=True)
                            
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": res["answer"],
                            "citations": res.get("citations", []),
                            "confidence_score": score,
                            "confidence_level": level,
                            "limitations": res.get("limitations", []),
                            "review_status": res.get("review_status", "PENDING_REVIEW"),
                            "audit_id": res.get("audit_id")
                        })
    with col_r:
        st.markdown("#### 💡 Suggested Architecture Queries")
        queries = [
            "What software layers comprise the AUTOSAR architecture?",
            "Explain the role of the Runtime Environment (RTE).",
            "What BSW modules manage communication and routing?",
            "How does EcuM handle ECU startup and shutdown?",
            "What interfaces connect Dem and Dcm diagnostics?"
        ]
        for q in queries:
            if st.button(q, key=f"sug_{q}"):
                st.session_state.messages.append({"role": "user", "content": q})
                res = query_assistant(q, active_proj)
                if res:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": res["answer"],
                        "citations": res.get("citations", []),
                        "confidence_score": res.get("confidence_score", 0.8),
                        "confidence_level": res.get("confidence_level", "HIGH"),
                        "limitations": res.get("limitations", []),
                        "review_status": res.get("review_status", "PENDING_REVIEW"),
                        "audit_id": res.get("audit_id")
                    })
                st.rerun()

# --- TAB 2: STRUCTURED INVENTORY & DEPENDENCY MAP ---
with tab_inv:
    st.subheader("🧩 Extracted Architecture Inventory")
    inv = fetch_inventory(active_proj)
    if inv:
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            st.markdown(f"<div class='metric-card'><div class='metric-val'>{inv['total_components']}</div><div class='metric-lbl'>Components (SWCs)</div></div>", unsafe_allow_html=True)
        with m2:
            st.markdown(f"<div class='metric-card'><div class='metric-val'>{inv['total_interfaces']}</div><div class='metric-lbl'>Interfaces</div></div>", unsafe_allow_html=True)
        with m3:
            st.markdown(f"<div class='metric-card'><div class='metric-val'>{inv.get('total_ports', 0)}</div><div class='metric-lbl'>Ports</div></div>", unsafe_allow_html=True)
        with m4:
            st.markdown(f"<div class='metric-card'><div class='metric-val'>{inv['total_dependencies']}</div><div class='metric-lbl'>Assembly Connectors</div></div>", unsafe_allow_html=True)
        with m5:
            st.markdown(f"<div class='metric-card'><div class='metric-val'>{len(inv.get('inconsistencies', []))}</div><div class='metric-lbl'>Observations</div></div>", unsafe_allow_html=True)
            
        st.markdown("---")
        st.markdown("#### 📦 Software Components (SWCs) & Modules")
        if inv["components"]:
            df_comp = pd.DataFrame(inv["components"])
            st.dataframe(df_comp[["name", "layer", "component_type", "source_page", "description"]], width=1200)
        else:
            st.info("No components extracted yet. Ingest an HLD PDF to populate the inventory.")
            
        st.markdown("#### 🔌 Architecture Interface Definitions")
        if inv["interfaces"]:
            df_if = pd.DataFrame(inv["interfaces"])
            st.dataframe(df_if[["name", "interface_type", "elements_or_operations", "source_page"]], width=1200)
        
        st.markdown("#### 🔗 Port Declarations")
        if inv.get("ports"):
            df_ports = pd.DataFrame(inv["ports"])
            st.dataframe(df_ports[["component_name", "port_name", "port_type", "interface_name", "source_page"]], width=1200)
        else:
            st.info("No ports extracted from the ingested documents.")
            
        st.markdown("#### 🔗 Component Dependency Map (Assembly Connectors)")
        if inv["dependencies"]:
            df_dep = pd.DataFrame(inv["dependencies"])
            st.dataframe(df_dep[["source_component", "target_component", "interface_name", "connector_type", "status"]], width=1200)
    else:
        st.info("No inventory found for this project.")

# --- TAB 3: REVISION COMPARISON & INCONSISTENCIES ---
with tab_diff:
    st.subheader("🔍 Revision Comparison & Inconsistency Analysis")
    st.markdown("Compare architecture across document revisions or specifications to detect added/removed SWCs, mutated interfaces, and architectural gaps.")
    
    docs_list = fetch_documents(active_proj)
    
    selected_base_id = None
    selected_target_id = None
    
    if docs_list:
        doc_options = {
            f"📄 {d['filename']} (v{d['version']}) — [{d['doc_id'][:8]}]": d['doc_id']
            for d in docs_list
        }
        option_labels = list(doc_options.keys())
        
        st.markdown("##### ⚙️ Select Document Revisions to Compare")
        col_b, col_t = st.columns(2)
        
        # Default base to second most recent (or first), target to most recent
        default_base_idx = min(1, len(option_labels) - 1) if len(option_labels) >= 2 else 0
        default_target_idx = 0
        
        with col_b:
            base_choice = st.selectbox(
                "📌 Baseline / Reference Document",
                options=option_labels,
                index=default_base_idx,
                help="Select the reference baseline revision (e.g. v1.0, older HLD spec)"
            )
            selected_base_id = doc_options[base_choice]
            
        with col_t:
            target_choice = st.selectbox(
                "🎯 Target / New Revision",
                options=option_labels,
                index=default_target_idx,
                help="Select the new target revision to evaluate against the baseline (e.g. v2.0, updated spec)"
            )
            selected_target_id = doc_options[target_choice]
            
        if len(docs_list) == 1:
            st.info("ℹ️ Only 1 document is ingested in this project. Comparing this document against itself runs an internal architectural completeness and orphaned-dependency audit. Ingest another revision or specification to perform a cross-revision delta analysis.")
    else:
        st.info("No documents found in this project. Ingest HLD PDFs from the sidebar to enable revision comparison.")

    # Run comparison using selected base and target IDs
    if selected_base_id and selected_target_id:
        comp_report = fetch_comparison(active_proj, doc_id_base=selected_base_id, doc_id_target=selected_target_id)
        if comp_report:
            st.markdown("---")
            st.success(f"**Baseline**: `{comp_report['base_document']}` ➔ **Target**: `{comp_report['target_document']}`")
            st.info(comp_report["summary"])
            
            # Delta metrics cards
            d1, d2, d3, d4 = st.columns(4)
            with d1:
                st.metric("Added SWCs", len(comp_report.get("added_components", [])))
            with d2:
                st.metric("Removed SWCs", len(comp_report.get("removed_components", [])))
            with d3:
                st.metric("Modified Interfaces", len(comp_report.get("modified_interfaces", [])))
            with d4:
                st.metric("Total Findings", len(comp_report.get("inconsistencies", [])))
                
            # If there are added/removed/modified elements, display them nicely
            if comp_report.get("added_components") or comp_report.get("removed_components") or comp_report.get("modified_interfaces"):
                with st.expander("📋 Detailed Revision Delta Matrix", expanded=True):
                    if comp_report.get("added_components"):
                        st.markdown("**🟢 Added Components in Target:**")
                        st.write(", ".join([f"`{c}`" for c in comp_report["added_components"]]))
                    if comp_report.get("removed_components"):
                        st.markdown("**🔴 Removed Components from Baseline:**")
                        st.write(", ".join([f"`{c}`" for c in comp_report["removed_components"]]))
                    if comp_report.get("modified_interfaces"):
                        st.markdown("**🟡 Modified Interface Contracts:**")
                        st.write(", ".join([f"`{i}`" for i in comp_report["modified_interfaces"]]))
            
            st.markdown("#### ⚠️ Architectural Inconsistency Findings & Alerts")
            if comp_report.get("inconsistencies"):
                for item in comp_report.get("inconsistencies", []):
                    sev = item["severity"]
                    sev_icon = "🔴" if sev == "ERROR" else ("🟡" if sev == "WARNING" else "🔵")
                    with st.expander(f"{sev_icon} [{sev}] {item['category']}: {item['component_or_interface']}", expanded=True):
                        st.markdown(f"**Description**: {item['description']}")
                        st.markdown(f"**Actionable Engineering Recommendation**: `{item['recommendation']}`")
            else:
                st.success("✅ No architectural inconsistencies, breaking changes, or orphaned dependencies detected between these revisions.")
        else:
            st.warning("Could not compute revision comparison report for the selected documents.")

# --- TAB 4: STRUCTURED EXPORT ---
with tab_export:
    st.subheader("📤 Export Structured Architecture Findings")
    st.markdown("Download extracted knowledge for downstream toolchains (Enterprise Architect, Vector CANoe, safety tracking, or audit dossier).")
    
    col_exp1, col_exp2, col_exp3 = st.columns(3)
    with col_exp1:
        st.markdown("##### 📄 Complete Architecture Dossier (JSON)")
        st.caption("Full inventory with components, ports, interfaces, dependencies, and inconsistency matrix in structured JSON format.")
        try:
            r = requests.get(f"{API_BASE_URL}/architecture/export?project_id={active_proj}&format=json", headers=get_auth_headers())
            if r.status_code == 200:
                st.download_button("Download JSON Findings", data=r.text, file_name=f"autosar_{active_proj}_findings.json", mime="application/json", use_container_width=True)
        except Exception:
            st.error("Export service offline")
            
    with col_exp2:
        st.markdown("##### 📊 Component Inventory (CSV)")
        st.caption("Spreadsheet-ready CSV of all extracted SWCs, layers, types, and source page citations.")
        try:
            r = requests.get(f"{API_BASE_URL}/architecture/export?project_id={active_proj}&format=csv", headers=get_auth_headers())
            if r.status_code == 200:
                st.download_button("Download Components CSV", data=r.text, file_name=f"autosar_{active_proj}_components.csv", mime="text/csv", use_container_width=True)
        except Exception:
            st.error("Export service offline")
            
    with col_exp3:
        st.markdown("##### 📝 Formal Engineering Report (Markdown)")
        st.caption("Formatted report with executive summary, tables, and governance review sign-off block.")
        try:
            r = requests.get(f"{API_BASE_URL}/architecture/export?project_id={active_proj}&format=markdown", headers=get_auth_headers())
            if r.status_code == 200:
                st.download_button("Download Markdown Report", data=r.text, file_name=f"autosar_{active_proj}_review_report.md", mime="text/markdown", use_container_width=True)
        except Exception:
            st.error("Export service offline")

# --- TAB 5: GOVERNANCE & AUDIT TRAIL ---
with tab_audit:
    st.subheader("🛡️ Engineering Governance & Audit Trail")
    st.markdown("Immutable record of all document uploads, queries, confidence scores, and specialist review dispositions.")
    
    audit_events = fetch_audit_logs(active_proj)
    if audit_events:
        df_audit = pd.DataFrame(audit_events)
        st.dataframe(df_audit[["id", "timestamp", "username", "role", "action", "confidence_score", "review_status", "query_text"]], width=1200)
        
        # Human Disposition Form (Admin / Architect)
        if role in ["admin", "architect"]:
            st.markdown("#### ✍️ Human-in-the-Loop Review Disposition")
            with st.form("disposition_form"):
                target_audit_id = st.selectbox("Select Audit Event ID to Review", options=[e["id"] for e in audit_events])
                new_disp = st.selectbox("Engineering Disposition Decision", ["ACCEPTED", "MODIFIED", "REJECTED"])
                notes = st.text_area("Review Comments / Rationale for Compliance Dossier")
                submit_disp = st.form_submit_button("Submit Sign-off Disposition", type="primary")
                if submit_disp:
                    success = submit_disposition(target_audit_id, new_disp, notes)
                    if success:
                        st.success(f"Audit event #{target_audit_id} disposition recorded as '{new_disp}'.")
                        st.rerun()
                    else:
                        st.error("Failed to record disposition.")
    else:
        st.info("No audit events recorded yet for this project.")
