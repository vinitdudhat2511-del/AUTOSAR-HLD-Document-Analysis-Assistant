import sys
import os
import io
import time

sys.path.insert(0, os.path.abspath("backend"))

from fastapi.testclient import TestClient
from app.main import app
from app.database import (
    SessionLocal, Document, ArchitectureComponent,
    ArchitectureInterface, ArchitecturePort, ArchitectureDependency
)

client = TestClient(app)

def run_feature_tests():
    print("=" * 600)
    print("RUNNING EXTENSIVE ARCHITECTURE & DIFF VALIDATION TESTS")
    print("=" * 60)

    # 1. Login as architect
    res = client.post("/api/v1/auth/login", json={"username": "architect_john", "password": "Arch@123"})
    assert res.status_code == 200, f"Login failed: {res.text}"
    token = res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("[PASS] Architect authentication: OK")

    # 2. Upload test PDF and verify ingestion + genuine extraction
    active_doc_id = None
    candidates = [
        "AUTOSAR_EXP_LayeredSoftwareArchitecture.pdf",
        "backend/uploads/AUTOSAR_EXP_LayeredSoftwareArchitecture.pdf",
        os.path.join(os.path.dirname(__file__), "uploads", "AUTOSAR_EXP_LayeredSoftwareArchitecture.pdf")
    ]
    pdf_path = next((p for p in candidates if os.path.exists(p)), None)
    if pdf_path:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        res = client.post(
            "/api/v1/upload",
            headers=headers,
            files={"file": ("AUTOSAR_EXP_LayeredSoftwareArchitecture.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"project_id": "AUTOSAR_Classic_BSW", "version": "4.4.0"}
        )
        assert res.status_code == 200, f"Upload failed: {res.text}"
        data = res.json()
        doc_id_1 = data["doc_id"]
        print(f"[PASS] Document Ingestion Accepted (doc_id: {doc_id_1[:8]})")

        # Verify async background status
        status_res = client.get(f"/api/v1/documents/{doc_id_1}/status", headers=headers)
        assert status_res.status_code == 200
        doc_stat = status_res.json()
        print(f"[PASS] Async Status Polling: OK (Status: '{doc_stat['status']}', Pages: {doc_stat['page_count']}, Chunks: {doc_stat['chunk_count']})")
        initial_chunks = doc_stat['chunk_count']

        # Query structured inventory after initial upload
        res_inv1 = client.get("/api/v1/architecture/inventory?project_id=AUTOSAR_Classic_BSW", headers=headers)
        assert res_inv1.status_code == 200
        inv1 = res_inv1.json()
        comps_count1 = inv1["total_components"]
        ifs_count1 = inv1["total_interfaces"]
        ports_count1 = inv1["total_ports"]
        deps_count1 = inv1["total_dependencies"]
        assert comps_count1 > 0, "Expected components to be extracted on initial upload"
        print(f"[PASS] Initial Architecture Extraction: {comps_count1} SWCs, {ifs_count1} Interfaces, {ports_count1} Ports, {deps_count1} Dependencies")

        # 3. Test Re-upload Deduplication: re-uploading the same file must replace, NOT duplicate
        # Re-upload 2nd time
        res_dup = client.post(
            "/api/v1/upload",
            headers=headers,
            files={"file": ("AUTOSAR_EXP_LayeredSoftwareArchitecture.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"project_id": "AUTOSAR_Classic_BSW", "version": "4.4.1"}
        )
        assert res_dup.status_code == 200
        dup_stat = client.get(f"/api/v1/documents/{res_dup.json()['doc_id']}/status", headers=headers).json()
        assert dup_stat["chunk_count"] == initial_chunks, f"Expected chunks {initial_chunks}, got {dup_stat['chunk_count']}"
        
        # Verify inventory did not double
        inv2 = client.get("/api/v1/architecture/inventory?project_id=AUTOSAR_Classic_BSW", headers=headers).json()
        assert inv2["total_components"] == comps_count1, f"Bug #1 Regression: Components duplicated on 2nd upload ({comps_count1} -> {inv2['total_components']})"
        assert inv2["total_interfaces"] == ifs_count1, f"Interfaces duplicated: {ifs_count1} -> {inv2['total_interfaces']}"
        assert inv2["total_ports"] == ports_count1, f"Ports duplicated: {ports_count1} -> {inv2['total_ports']}"
        assert inv2["total_dependencies"] == deps_count1, f"Dependencies duplicated: {deps_count1} -> {inv2['total_dependencies']}"

        # Re-upload 3rd time (simulating repeated revisions)
        res_dup3 = client.post(
            "/api/v1/upload",
            headers=headers,
            files={"file": ("AUTOSAR_EXP_LayeredSoftwareArchitecture.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
            data={"project_id": "AUTOSAR_Classic_BSW", "version": "4.4.2"}
        )
        assert res_dup3.status_code == 200
        inv3 = client.get("/api/v1/architecture/inventory?project_id=AUTOSAR_Classic_BSW", headers=headers).json()
        assert inv3["total_components"] == comps_count1, f"Bug #1 Regression: Components duplicated on 3rd upload ({comps_count1} -> {inv3['total_components']})"
        print(f"[PASS] Re-upload Inventory Deduplication: OK (Stable at {inv3['total_components']} SWCs across 3 uploads, zero duplication)")

        # 3b. Test Multi-Document Project Accumulation (Bug #2 prevention)
        # Adding document B into the same project must NOT wipe document A's ports/dependencies
        active_doc_id = res_dup3.json()["doc_id"]
        db_multi = SessionLocal()
        doc_b_id = "doc-b-simulated-interfaces-id"
        try:
            doc_b = Document(
                doc_id=doc_b_id,
                filename="AUTOSAR_SWS_DiagnosticInterfaces.pdf",
                stored_path="simulated_doc_b.pdf",
                project_id="AUTOSAR_Classic_BSW",
                uploaded_by="architect_john",
                version="1.0",
                status="processed",
                page_count=45,
                chunk_count=80
            )
            db_multi.add(doc_b)
            # Add doc B specific port and dependency
            port_b = ArchitecturePort(
                project_id="AUTOSAR_Classic_BSW",
                doc_id=doc_b_id,
                component_name="Dem",
                port_name="PPort_DiagnosticEventData",
                port_type="PPort",
                interface_name="DiagnosticEventData_SR_If",
                source_page=14
            )
            db_multi.add(port_b)
            dep_b = ArchitectureDependency(
                project_id="AUTOSAR_Classic_BSW",
                doc_id=doc_b_id,
                source_component="Dem",
                target_component="Dcm",
                interface_name="DiagnosticEventData_SR_If",
                connector_type="Assembly",
                status="Connected"
            )
            db_multi.add(dep_b)
            db_multi.commit()

            # Verify inventory now accumulates entities from both documents
            inv_multi = client.get("/api/v1/architecture/inventory?project_id=AUTOSAR_Classic_BSW", headers=headers).json()
            port_names = [p["port_name"] for p in inv_multi["ports"]]
            assert "PPort_DiagnosticEventData" in port_names, "Doc B port not found in project inventory!"
            assert inv_multi["total_ports"] == ports_count1 + 1, f"Expected {ports_count1 + 1} ports, got {inv_multi['total_ports']}"
            assert inv_multi["total_dependencies"] == deps_count1 + 1, f"Expected {deps_count1 + 1} dependencies, got {inv_multi['total_dependencies']}"
            print(f"[PASS] Multi-Document Accumulation: OK (Doc A and Doc B ports & dependencies co-exist without project-wide wipe)")
        finally:
            db_multi.query(ArchitecturePort).filter(ArchitecturePort.doc_id == doc_b_id).delete()
            db_multi.query(ArchitectureDependency).filter(ArchitectureDependency.doc_id == doc_b_id).delete()
            db_multi.query(Document).filter(Document.doc_id == doc_b_id).delete()
            db_multi.commit()
            db_multi.close()

    else:
        print("[WARN] Sample PDF not found in workspace, skipping live PDF upload test")

    # 4. Check Genuine Structured Architecture Inventory & False Positive Filter
    res = client.get("/api/v1/architecture/inventory?project_id=AUTOSAR_Classic_BSW", headers=headers)
    assert res.status_code == 200, f"Inventory failed: {res.text}"
    inv = res.json()
    assert inv["total_components"] > 0, "Expected components to be extracted"
    # Ensure no naked single-word false positive modules exist
    comp_names = [c["name"] for c in inv["components"]]
    assert "Can" not in comp_names, "Naked 'Can' single-word false positive found!"
    assert "Driver" not in comp_names, "Generic 'Driver' false positive found!"
    assert "Wireless" not in comp_names, "Generic 'Wireless' false positive found!"
    if_names = [i["name"] for i in inv["interfaces"]]
    assert "Driver" not in if_names, "Generic 'Driver' false positive interface found!"
    assert "External" not in if_names, "Generic 'External' false positive interface found!"
    assert "Services" not in if_names, "Generic 'Services' false positive interface found!"
    assert "Service" not in if_names, "Generic 'Service' false positive interface found!"
    print(f"[PASS] False Positive Blocklist Filter: OK (No generic noise terms in SWCs or Interfaces, including 'Services')")

    # 5. Check Real Document Revision Diff Engine
    # Create a simulated second revision to test real diff calculations
    db = SessionLocal()
    try:
        # Add a simulated revision 2 document with an added component and modified interface
        doc_2 = Document(
            doc_id="test-rev-2-id",
            filename="AUTOSAR_EXP_LayeredArchitecture_v5.pdf",
            stored_path="simulated_v5.pdf",
            project_id="AUTOSAR_Classic_BSW",
            uploaded_by="architect_john",
            version="5.0.0",
            status="processed",
            page_count=180,
            chunk_count=310
        )
        db.add(doc_2)
        # Add an added component in v5.0
        db.add(ArchitectureComponent(
            project_id="AUTOSAR_Classic_BSW",
            doc_id="test-rev-2-id",
            name="Crypto_Service_Manager",
            component_type="BSW Module",
            layer="Services",
            description="Cryptographic primitives and key management services added in revision 5.0.",
            source_page=12
        ))
        # Add an existing component for continuity
        db.add(ArchitectureComponent(
            project_id="AUTOSAR_Classic_BSW",
            doc_id="test-rev-2-id",
            name="EcuM",
            component_type="BSW Module",
            layer="Services",
            description="ECU State Manager",
            source_page=15
        ))
        # Add a modified interface
        db.add(ArchitectureInterface(
            project_id="AUTOSAR_Classic_BSW",
            doc_id="test-rev-2-id",
            name="DiagnosticSession_CS_Interface",
            interface_type="Client-Server (V2 Extended)",
            elements_or_operations="RequestSession(uint8), SecurityKeyAuth(uint32)",
            source_page=20
        ))
        db.commit()

        # Run Revision Diff
        res_diff = client.post(
            "/api/v1/architecture/compare",
            headers=headers,
            json={"project_id": "AUTOSAR_Classic_BSW", "doc_id_base": active_doc_id, "doc_id_target": "test-rev-2-id"}
        )
        assert res_diff.status_code == 200
        diff_report = res_diff.json()
        print(f"[PASS] Real Revision Diff Engine: OK")
        print(f"       Added SWCs: {diff_report['added_components']}")
        print(f"       Removed SWCs: {len(diff_report['removed_components'])}")
        print(f"       Inconsistencies/Alerts: {len(diff_report['inconsistencies'])}")
        assert "Crypto_Service_Manager" in diff_report["added_components"], "Expected added SWC in diff!"
        assert len(diff_report["inconsistencies"]) > 0, "Expected inconsistency alerts on diff!"

        # Cleanup test revision
        db.query(ArchitectureComponent).filter(ArchitectureComponent.doc_id == "test-rev-2-id").delete()
        db.query(ArchitectureInterface).filter(ArchitectureInterface.doc_id == "test-rev-2-id").delete()
        db.query(Document).filter(Document.doc_id == "test-rev-2-id").delete()
        db.commit()
    finally:
        db.close()

    # 6. Check Structured Exports (JSON, CSV, Markdown)
    res_json = client.get("/api/v1/architecture/export?project_id=AUTOSAR_Classic_BSW&format=json", headers=headers)
    assert res_json.status_code == 200
    print("[PASS] JSON Export: OK")

    res_csv = client.get("/api/v1/architecture/export?project_id=AUTOSAR_Classic_BSW&format=csv", headers=headers)
    assert res_csv.status_code == 200 and "Name,Type,Layer" in res_csv.text
    print("[PASS] CSV Export: OK")

    res_md = client.get("/api/v1/architecture/export?project_id=AUTOSAR_Classic_BSW&format=markdown", headers=headers)
    assert res_md.status_code == 200 and "Executive Summary" in res_md.text
    print("[PASS] Markdown Report Export: OK")

    # 7. Check Governance Audit Trail & Review Disposition
    res_audit = client.get("/api/v1/audit/logs?project_id=AUTOSAR_Classic_BSW", headers=headers)
    assert res_audit.status_code == 200
    logs = res_audit.json()
    assert len(logs) > 0, "Expected audit events"
    target_id = logs[0]["id"]
    print(f"[PASS] Audit Logging: OK ({len(logs)} audit events tracked)")

    res_disp = client.post(
        "/api/v1/audit/disposition",
        headers=headers,
        json={"audit_id": target_id, "disposition": "ACCEPTED", "notes": "Verified by AUTOSAR Architect"}
    )
    assert res_disp.status_code == 200
    print("[PASS] Human-in-the-Loop Governance Disposition: OK")

    # 8. Concrete Project HLD Port Extraction Test
    # Tests extraction on a project HLD with real named port declarations (PPort_*, RPort_*, P_*, R_*, Pp*, Rp*, PRPort_*)
    import pymupdf
    test_pdf_path = "test_project_hld_ports.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page()
    page.insert_text((50, 50), """
    AUTOSAR High-Level Design Specification: Powertrain Gateway ECU
    
    1. Software Components and Port Interfaces
    The EngineControl_SWC manages engine timing and throttle actuators.
    It defines the following port declarations:
    - Provided Port PPort_EngineSpeed provides engine rotation velocity to other components.
    - Required Port RPort_VehicleSpeed requires vehicle road speed signals.
    - P-Port P_WheelSpeed provides high-resolution wheel ticks.
    - R-Port R_BrakePedalPosition requires braking sensor inputs.
    - PpMotorTorque provides electrical motor torque requests.
    - RpBatteryState requires state-of-charge measurements.
    - Provided-Required Port PRPort_ModeArbitration coordinates powertrain operating modes.
    - Provided Port: ThrottlePosition indicates throttle valve angle.
    - Required Port: GearStatus indicates active transmission gear.
    
    CanIf provides services to PduR.
    EngineControl_SWC communicates with BswM.
    """)
    doc_pdf.save(test_pdf_path)
    doc_pdf.close()
    
    try:
        with open(test_pdf_path, "rb") as f:
            hld_bytes = f.read()
        res_hld = client.post(
            "/api/v1/upload",
            headers=headers,
            files={"file": (test_pdf_path, io.BytesIO(hld_bytes), "application/pdf")},
            data={"project_id": "Powertrain_Gateway", "version": "1.0.0"}
        )
        assert res_hld.status_code == 200
        
        inv_hld = client.get("/api/v1/architecture/inventory?project_id=Powertrain_Gateway", headers=headers).json()
        port_names = [p["port_name"] for p in inv_hld["ports"]]
        port_types = {p["port_name"]: p["port_type"] for p in inv_hld["ports"]}
        
        print(f"[PASS] Concrete Project HLD Port Extraction: Extracted {len(port_names)} ports: {port_names}")
        assert len(port_names) >= 7, f"Expected at least 7 ports from concrete HLD, got {len(port_names)}"
        assert "PPort_EngineSpeed" in port_names
        assert "RPort_VehicleSpeed" in port_names
        assert "P_WheelSpeed" in port_names
        assert "R_BrakePedalPosition" in port_names
        assert "PpMotorTorque" in port_names
        assert "RpBatteryState" in port_names
        assert "PRPort_ModeArbitration" in port_names
        assert port_types["PPort_EngineSpeed"] == "PPort"
        assert port_types["RPort_VehicleSpeed"] == "RPort"
        assert port_types["PRPort_ModeArbitration"] == "PRPort"
        print("[PASS] Port Type Categorization: OK (PPort, RPort, and PRPort correctly classified)")
    finally:
        if os.path.exists(test_pdf_path):
            try:
                os.remove(test_pdf_path)
            except Exception:
                pass
        db_clean = SessionLocal()
        try:
            db_clean.query(ArchitecturePort).filter(ArchitecturePort.project_id == "Powertrain_Gateway").delete()
            db_clean.query(ArchitectureComponent).filter(ArchitectureComponent.project_id == "Powertrain_Gateway").delete()
            db_clean.query(ArchitectureInterface).filter(ArchitectureInterface.project_id == "Powertrain_Gateway").delete()
            db_clean.query(ArchitectureDependency).filter(ArchitectureDependency.project_id == "Powertrain_Gateway").delete()
            db_clean.query(Document).filter(Document.project_id == "Powertrain_Gateway").delete()
            db_clean.commit()
        finally:
            db_clean.close()

    print("=" * 60)
    print("ALL ARCHITECTURE & DIFF VALIDATION TESTS PASSED!")
    print("=" * 60)

if __name__ == "__main__":
    run_feature_tests()
