import json
import io
import csv
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.services.extractor import get_project_inventory
from app.services.comparator import compare_documents_or_revisions
from app.database import AuditLog

def export_project_findings_json(project_id: str, db: Session) -> str:
    """Export complete project findings as formatted JSON."""
    inventory = get_project_inventory(project_id, db)
    comparison = compare_documents_or_revisions(project_id, None, None, db)
    
    export_payload = {
        "export_metadata": {
            "project_id": project_id,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "standard": "AUTOSAR Classic / Adaptive HLD Reference Standard"
        },
        "inventory": inventory.model_dump(),
        "comparison_and_inconsistencies": comparison.model_dump()
    }
    return json.dumps(export_payload, indent=2)

def export_components_csv(project_id: str, db: Session) -> str:
    """Export component inventory as CSV."""
    inventory = get_project_inventory(project_id, db)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Type", "Layer", "Source_Page", "Description"])
    for c in inventory.components:
        writer.writerow([c.name, c.component_type, c.layer, c.source_page, c.description])
    return output.getvalue()

def export_engineering_report_markdown(project_id: str, db: Session) -> str:
    """Generate professional Markdown Architecture Engineering Review Report."""
    inventory = get_project_inventory(project_id, db)
    comparison = compare_documents_or_revisions(project_id, None, None, db)
    audit_count = db.query(AuditLog).filter(AuditLog.project_id == project_id).count()
    
    md = []
    md.append(f"# AUTOSAR High-Level Design (HLD) Architecture Analysis Report")
    md.append(f"**Program / Project ID**: `{project_id}`  ")
    md.append(f"**Report Generated**: `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}`  ")
    md.append(f"**Governance Audit Events Tracked**: `{audit_count}`  ")
    md.append("\n---\n")
    
    md.append("## 1. Executive Summary")
    md.append(
        f"Automated architectural knowledge extraction identified **{inventory.total_components} software components**, "
        f"**{inventory.total_interfaces} interface contracts**, **{inventory.total_ports} port declarations**, "
        f"and **{inventory.total_dependencies} assembly connectors**. "
        f"Completeness checks uncovered **{len(comparison.inconsistencies)} architectural observations** requiring specialist review."
    )
    
    md.append("\n## 2. Software Component Inventory")
    md.append("| Component Name | Layer | Type | Source Page | Description |")
    md.append("| :--- | :--- | :--- | :--- | :--- |")
    for c in inventory.components:
        md.append(f"| **{c.name}** | {c.layer} | {c.component_type} | Page {c.source_page} | {c.description} |")
        
    md.append("\n## 3. Interface Definitions")
    md.append("| Interface Name | Interface Type | Operations / Data Elements |")
    md.append("| :--- | :--- | :--- |")
    for i in inventory.interfaces:
        md.append(f"| `{i.name}` | {i.interface_type} | {i.elements_or_operations} |")
    
    md.append("\n## 4. Port Declarations")
    md.append("| Component | Port Name | Port Type | Interface | Source Page |")
    md.append("| :--- | :--- | :--- | :--- | :--- |")
    for p in inventory.ports:
        md.append(f"| `{p.component_name}` | `{p.port_name}` | {p.port_type} | {p.interface_name or '—'} | Page {p.source_page} |")
        
    md.append("\n## 5. Component Dependencies & Assembly Connectors")
    md.append("| Source Component | Target Component | Interface | Connector Type | Status |")
    md.append("| :--- | :--- | :--- | :--- | :--- |")
    for d in inventory.dependencies:
        md.append(f"| `{d.source_component}` | `{d.target_component}` | `{d.interface_name}` | {d.connector_type} | **{d.status}** |")
        
    md.append("\n## 6. Architectural Inconsistency & Completeness Observations")
    for inc in comparison.inconsistencies:
        md.append(f"### [{inc.severity}] {inc.category}: {inc.component_or_interface}")
        md.append(f"- **Observation**: {inc.description}")
        md.append(f"- **Actionable Recommendation**: {inc.recommendation}")
        md.append("")
        
    md.append("\n## 7. Architecture Governance Sign-off")
    md.append("> *Governance Principle: AI-generated architecture content must be traceable to approved source material and reviewed by authorized engineering specialists before it is used for compliance, design approval, software release, or vehicle validation.*")
    md.append("\n- [ ] System Architect Approval: _____________________  Date: __________")
    md.append("- [ ] Safety & Cybersecurity Sign-off: _______________  Date: __________")
    
    return "\n".join(md)
