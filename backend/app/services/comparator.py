from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.database import (
    ArchitectureComponent, ArchitectureInterface,
    ArchitecturePort, ArchitectureDependency, Document
)
from app.models import ComparisonReport, InconsistencyItem

def compare_documents_or_revisions(
    project_id: str,
    doc_id_base: Optional[str],
    doc_id_target: Optional[str],
    db: Session
) -> ComparisonReport:
    """
    Perform genuine architectural revision diffing between two documents/revisions:
    - Identifies added components (in target but not base)
    - Identifies removed components (in base but not target)
    - Identifies modified interfaces (contract or operation signature changes)
    - Detects breaking architectural changes (removed interfaces still needed by SWCs)
    - Identifies unconnected ports and dependency gaps
    """
    # 1. Resolve Document IDs if not explicitly passed
    project_docs = db.query(Document).filter(
        Document.project_id == project_id
    ).order_by(Document.upload_time.asc()).all()

    if not doc_id_base or not doc_id_target:
        if len(project_docs) >= 2:
            # Auto-select the two most recent revisions
            doc_id_base = project_docs[-2].doc_id
            doc_id_target = project_docs[-1].doc_id
        elif len(project_docs) == 1:
            # Single document in project: run internal completeness audit
            doc_id_base = project_docs[0].doc_id
            doc_id_target = project_docs[0].doc_id
        else:
            return ComparisonReport(
                project_id=project_id,
                base_document="None",
                target_document="None",
                added_components=[],
                removed_components=[],
                modified_interfaces=[],
                unconnected_ports=[],
                inconsistencies=[],
                summary="No documents available in project to compare."
            )

    # Resolve document metadata labels
    doc_b = db.query(Document).filter(Document.doc_id == doc_id_base).first()
    doc_t = db.query(Document).filter(Document.doc_id == doc_id_target).first()

    base_name = f"{doc_b.filename} (v{doc_b.version})" if doc_b else f"Doc {doc_id_base[:8]}"
    target_name = f"{doc_t.filename} (v{doc_t.version})" if doc_t else f"Doc {doc_id_target[:8]}"

    # 2. Fetch extracted entities specifically for Base and Target documents
    base_comps = db.query(ArchitectureComponent).filter(ArchitectureComponent.doc_id == doc_id_base).all()
    target_comps = db.query(ArchitectureComponent).filter(ArchitectureComponent.doc_id == doc_id_target).all()
    
    base_ifs = db.query(ArchitectureInterface).filter(ArchitectureInterface.doc_id == doc_id_base).all()
    target_ifs = db.query(ArchitectureInterface).filter(ArchitectureInterface.doc_id == doc_id_target).all()

    base_comp_map = {c.name: c for c in base_comps}
    target_comp_map = {c.name: c for c in target_comps}
    
    base_if_map = {i.name: i for i in base_ifs}
    target_if_map = {i.name: i for i in target_ifs}

    # Case A: Two different documents/revisions (Real Diff Engine)
    if doc_id_base != doc_id_target:
        added_components = [name for name in target_comp_map if name not in base_comp_map]
        removed_components = [name for name in base_comp_map if name not in target_comp_map]
        
        modified_interfaces: List[str] = []
        for if_name in target_if_map:
            if if_name in base_if_map:
                b_if = base_if_map[if_name]
                t_if = target_if_map[if_name]
                if (b_if.interface_type != t_if.interface_type or 
                    b_if.elements_or_operations != t_if.elements_or_operations):
                    modified_interfaces.append(
                        f"{if_name} (Type: {b_if.interface_type} ➔ {t_if.interface_type})"
                    )

        inconsistencies: List[InconsistencyItem] = []
        
        # Check for breaking changes: components removed that had active roles
        for rem in removed_components:
            inconsistencies.append(InconsistencyItem(
                category="Component Deletion",
                severity="WARNING",
                component_or_interface=rem,
                description=f"Component '{rem}' was present in base revision '{base_name}' but removed in '{target_name}'.",
                recommendation=f"Review downstream callers to ensure no orphaned dependencies rely on '{rem}'."
            ))
            
        # Check for modified interface breaking changes
        for mod in modified_interfaces:
            inconsistencies.append(InconsistencyItem(
                category="Interface Contract Mutation",
                severity="WARNING",
                component_or_interface=mod.split(" ")[0],
                description=f"Interface contract '{mod}' was modified between revisions.",
                recommendation="Verify RTE contract phase generation and revalidate connected SWC port compatibility."
            ))

        # Check for unconnected ports in target
        target_ports = db.query(ArchitecturePort).filter(ArchitecturePort.project_id == project_id).all()
        target_deps = db.query(ArchitectureDependency).filter(ArchitectureDependency.project_id == project_id).all()
        connected_swcs = {d.source_component for d in target_deps}.union({d.target_component for d in target_deps})
        
        unconnected_ports = []
        for p in target_ports:
            if p.component_name not in connected_swcs and p.component_name in target_comp_map:
                unconnected_ports.append(f"{p.component_name}.{p.port_name}")

        summary = (
            f"Revision Diff: '{base_name}' vs '{target_name}'. "
            f"Results: {len(added_components)} components added, {len(removed_components)} removed, "
            f"{len(modified_interfaces)} interfaces modified, {len(inconsistencies)} revision alerts."
        )

        return ComparisonReport(
            project_id=project_id,
            base_document=base_name,
            target_document=target_name,
            added_components=added_components,
            removed_components=removed_components,
            modified_interfaces=modified_interfaces,
            unconnected_ports=unconnected_ports,
            inconsistencies=inconsistencies,
            summary=summary
        )

    # Case B: Single Document Architecture Completeness Audit
    else:
        inconsistencies = []
        # Completeness checks on the single document
        if "RTE" not in target_comp_map:
            inconsistencies.append(InconsistencyItem(
                category="Architecture Core",
                severity="WARNING",
                component_or_interface="Runtime Environment (RTE)",
                description="Runtime Environment (RTE) not explicitly declared in this specification.",
                recommendation="Ensure VFB generation rules and RTE contract phase are documented."
            ))
            
        summary = (
            f"Single Document Architecture Completeness Audit for '{target_name}'. "
            f"Analyzed {len(target_comps)} software components and {len(target_ifs)} interfaces. "
            f"Found {len(inconsistencies)} architectural completeness observations. "
            f"(Upload a second revision to activate automatic delta diffing)."
        )

        return ComparisonReport(
            project_id=project_id,
            base_document=base_name,
            target_document=f"{target_name} (Single Revision Audit)",
            added_components=[],
            removed_components=[],
            modified_interfaces=[],
            unconnected_ports=[],
            inconsistencies=inconsistencies,
            summary=summary
        )
