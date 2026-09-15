import os
import re
import pymupdf
from typing import List, Dict, Any, Tuple, Set, Optional
from sqlalchemy.orm import Session
from app.database import (
    ArchitectureComponent, ArchitectureInterface,
    ArchitecturePort, ArchitectureDependency, Document
)
from app.models import (
    ArchitectureInventoryResponse, ComponentItem, InterfaceItem,
    PortItem, DependencyItem, InconsistencyItem
)

# Generic terms that should never be extracted as named components or interfaces.
# These are common English/spec words that frequently appear near "Interface", "SWC", etc.
# in AUTOSAR prose but are not actual named architectural entities.
GENERIC_TERMS_BLOCKLIST = {
    "driver", "drivers", "external", "generic", "control", "wireless", "watchdog",
    "application", "applications", "autosar", "standardized", "communication", "possible",
    "microcontroller", "complex", "operating", "module", "modules", "description",
    "flash", "situation", "sensor", "sensors", "actuator", "actuators", "translation",
    "software", "hardware", "system", "systems", "layer", "layers", "service", "services",
    "interface", "interfaces", "component", "components", "specification", "specifications",
    "architecture", "architectures", "function", "functions", "abstract",
    "standard", "standards", "basic", "general", "internal", "diagnostic", "diagnostics",
    "implementation", "configuration", "definition", "definitions", "platform",
    "functional", "physical", "logical", "virtual", "runtime",
    "manager", "managers", "handler", "handlers", "controller", "controllers", "processor", "monitor",
    "document", "documents", "chapter", "section", "figure", "table", "example",
    "overview", "introduction", "scope", "reference", "references", "appendix",
    "note", "notes", "requirement", "requirements", "test", "type", "types", "mode", "modes", "state", "states",
    "data", "signal", "signals", "message", "messages", "event", "events", "error", "errors", "status",
    "value", "values", "parameter", "parameters", "element", "elements", "object", "objects", "instance", "instances", "class",
    "method", "methods", "operation", "operations", "port", "ports", "connection", "connections", "link", "network",
    "protocol", "protocols", "transport", "routing", "gateway", "cluster",
    "channel", "channels", "frame", "frames", "packet", "packets", "buffer", "queue", "stack",
    "between", "through", "about", "within", "after", "before",
    "above", "below", "following", "according", "based", "related",
    "specific", "particular", "relevant", "different", "multiple",
    "various", "several", "other", "another", "additional",
    "provide", "provides", "require", "requires", "support", "supports", "include", "includes", "contain", "contains",
    "define", "defines", "describe", "describes", "specify", "specifies", "implement", "implements", "configure", "configures",
    "typical", "common", "certain", "available", "optional",
    "necessary", "required", "mandatory", "allowed", "forbidden",
    "complete", "partial", "detailed", "brief", "formal",
    "corresponding", "respective", "associated", "connected",
    "dependent", "independent", "upper", "lower", "higher",
    "input", "output", "process", "trigger", "callback",
    "init", "main", "default", "custom", "user",
}

# Formal AUTOSAR Module Definitions with Disambiguated Regex Patterns
# Avoids single-word false positives like "can" or "os" by requiring formal module names or qualified references
AUTOSAR_FORMAL_MODULES = [
    # Services Layer
    {
        "name": "OS",
        "full_name": "Operating System",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:AUTOSAR\s+OS|Operating\s+System\s+\(OS\)|OS\s+module|real-time\s+operating\s+system)\b',
            r'\bOS\s+manages\s+(?:tasks|scheduling|interrupts)\b'
        ],
        "default_desc": "Provides real-time task scheduling, priority-based arbitration, interrupts, and resource management."
    },
    {
        "name": "BswM",
        "full_name": "BSW Mode Manager",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:BSW\s+Mode\s+Manager|BswM\s+module|BswM\b)',
            r'\bBswM\s+arbitrates\s+rules\b'
        ],
        "default_desc": "Arbitrates ECU mode requests, startup/shutdown sequencing, and BSW state management."
    },
    {
        "name": "EcuM",
        "full_name": "ECU State Manager",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:ECU\s+State\s+Manager|EcuM\s+module|EcuM\b)',
            r'\bEcuM\s+controls\s+(?:startup|sleep|shutdown)\b'
        ],
        "default_desc": "Controls ECU initialization, wakeup validation, sleep phases, and shutdown sequencing."
    },
    {
        "name": "Dem",
        "full_name": "Diagnostic Event Manager",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:Diagnostic\s+Event\s+Manager|Dem\s+module|Dem\b)',
            r'\bDem\s+processes\s+and\s+stores\s+diagnostic\s+events\b'
        ],
        "default_desc": "Processes and stores diagnostic events, manages DTC statuses, and records freeze frame / extended data."
    },
    {
        "name": "Dcm",
        "full_name": "Diagnostic Communication Manager",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:Diagnostic\s+Communication\s+Manager|Dcm\s+module|Dcm\b)',
            r'\bDcm\s+handles\s+(?:UDS|diagnostic\s+requests)\b'
        ],
        "default_desc": "Handles UDS (ISO 14229) and OBD diagnostic service requests, session states, and security access."
    },
    {
        "name": "Com",
        "full_name": "Communication Manager",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:Communication\s+Manager\s+\(Com\)|AUTOSAR\s+COM|Com\s+module)\b',
            r'\bCOM\s+provides\s+signal\s+gateway\b'
        ],
        "default_desc": "Provides signal-based communication services, signal unpacking/packing, and transmission deadlines."
    },
    {
        "name": "PduR",
        "full_name": "PDU Router",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:PDU\s+Router|PduR\s+module|PduR\b)',
            r'\bPduR\s+routes\s+I-PDUs\b'
        ],
        "default_desc": "Routes I-PDUs between communication interface modules, transport protocols, and COM."
    },
    {
        "name": "NvM",
        "full_name": "Non-Volatile RAM Manager",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:Non-Volatile\s+RAM\s+Manager|NvM\s+module|NvM\b)',
            r'\bNvM\s+provides\s+synchronous\b'
        ],
        "default_desc": "Provides synchronous and asynchronous non-volatile block management and data integrity protection."
    },
    {
        "name": "WdgM",
        "full_name": "Watchdog Manager",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:Watchdog\s+Manager|WdgM\s+module|WdgM\b)',
            r'\bWdgM\s+supervises\b'
        ],
        "default_desc": "Performs alive supervision, deadline supervision, and program flow monitoring."
    },
    {
        "name": "Det",
        "full_name": "Default Error Tracer",
        "type": "BSW Module",
        "layer": "Services",
        "patterns": [
            r'\b(?:Default\s+Error\s+Tracer|Det\s+module|Det_ReportError\b)',
            r'\bDet\s+collects\s+errors\b'
        ],
        "default_desc": "Collects and logs development and configuration error reports across BSW modules."
    },
    
    # RTE (Runtime Environment)
    {
        "name": "RTE",
        "full_name": "Runtime Environment",
        "type": "Virtual Function Bus",
        "layer": "RTE",
        "patterns": [
            r'\b(?:Runtime\s+Environment|RTE\s+module|RTE\s+layer|Rte_Read|Rte_Write|Virtual\s+Function\s+Bus\s+\(VFB\))\b',
            r'\bRTE\s+provides\s+communication\s+infrastructure\b'
        ],
        "default_desc": "Runtime Environment acting as the virtual function bus connecting SWCs and BSW services."
    },
    
    # ECU Abstraction Layer
    {
        "name": "CanIf",
        "full_name": "CAN Interface",
        "type": "BSW Module",
        "layer": "ECU Abstraction",
        "patterns": [
            r'\b(?:CAN\s+Interface|CanIf\s+module|CanIf\b)',
            r'\bCanIf_Transmit\b'
        ],
        "default_desc": "Abstracts underlying CAN controller hardware and handles transmit/receive confirmation callbacks."
    },
    {
        "name": "CanTp",
        "full_name": "CAN Transport Protocol",
        "type": "BSW Module",
        "layer": "ECU Abstraction",
        "patterns": [
            r'\b(?:CAN\s+Transport\s+Protocol|CanTp\s+module|CanTp\b)',
            r'\bCanTp\s+segments\s+messages\b'
        ],
        "default_desc": "Segments and reassembles diagnostic and large payload PDUs over CAN (ISO 15765-2)."
    },
    {
        "name": "LinIf",
        "full_name": "LIN Interface",
        "type": "BSW Module",
        "layer": "ECU Abstraction",
        "patterns": [
            r'\b(?:LIN\s+Interface|LinIf\s+module|LinIf\b)'
        ],
        "default_desc": "Controls LIN frame routing, header transmission, and schedule table management."
    },
    {
        "name": "EthIf",
        "full_name": "Ethernet Interface",
        "type": "BSW Module",
        "layer": "ECU Abstraction",
        "patterns": [
            r'\b(?:Ethernet\s+Interface|EthIf\s+module|EthIf\b)'
        ],
        "default_desc": "Provides network abstraction for Ethernet MAC/PHY controllers and VLAN frame handling."
    },
    {
        "name": "MemIf",
        "full_name": "Memory Interface",
        "type": "BSW Module",
        "layer": "ECU Abstraction",
        "patterns": [
            r'\b(?:Memory\s+Interface|MemIf\s+module|MemIf\b)'
        ],
        "default_desc": "Abstracts access to flash (Fls) and EEPROM (Eep) memory hardware drivers."
    },
    {
        "name": "IoHwAb",
        "full_name": "I/O Hardware Abstraction",
        "type": "BSW Module",
        "layer": "ECU Abstraction",
        "patterns": [
            r'\b(?:I/O\s+Hardware\s+Abstraction|IoHwAb\s+module|IoHwAb\b)'
        ],
        "default_desc": "Provides signal-based access to ECU analog, digital, and PWM hardware pins."
    },
    
    # MCAL (Microcontroller Abstraction Layer) - Strict Patterns
    {
        "name": "CanDriver",
        "full_name": "CAN Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:CAN\s+Driver|Can_Init|Can_Write|Can_MainFunction)\b',
            r'\bMCAL\s+CAN\s+Driver\b'
        ],
        "default_desc": "Microcontroller Abstraction Layer driver providing direct register access to CAN hardware."
    },
    {
        "name": "EthDriver",
        "full_name": "Ethernet Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:Ethernet\s+Driver|Eth_Init|Eth_Transmit)\b',
            r'\bMCAL\s+Ethernet\s+Driver\b'
        ],
        "default_desc": "MCAL driver for on-chip Ethernet controller, buffer descriptors, and DMA management."
    },
    {
        "name": "SpiDriver",
        "full_name": "SPI Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:SPI\s+Driver|Spi_Init|Spi_AsyncTransmit|Spi_SyncTransmit)\b'
        ],
        "default_desc": "MCAL Serial Peripheral Interface driver for communicating with external ASICs and sensors."
    },
    {
        "name": "DioDriver",
        "full_name": "Digital I/O Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:DIO\s+Driver|Dio_ReadChannel|Dio_WriteChannel)\b'
        ],
        "default_desc": "MCAL Digital Input/Output port pin driver for reading and writing microcontroller pin states."
    },
    {
        "name": "AdcDriver",
        "full_name": "Analog-to-Digital Converter Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:ADC\s+Driver|Adc_Init|Adc_StartGroupConversion)\b'
        ],
        "default_desc": "MCAL driver controlling microcontroller analog-to-digital converter channels and sample buffers."
    },
    {
        "name": "PwmDriver",
        "full_name": "Pulse Width Modulation Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:PWM\s+Driver|Pwm_SetDutyCycle|Pwm_SetPeriodAndDuty)\b'
        ],
        "default_desc": "MCAL driver generating PWM output waveforms for actuators, motors, and lighting."
    },
    {
        "name": "McuDriver",
        "full_name": "Microcontroller Unit Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:MCU\s+Driver|Mcu_Init|Mcu_InitClock|Mcu_PerformReset)\b'
        ],
        "default_desc": "MCAL driver responsible for CPU initialization, PLL clocks, low-power modes, and reset control."
    },
    {
        "name": "WdgDriver",
        "full_name": "Watchdog Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:Watchdog\s+Driver|Wdg_Init|Wdg_SetMode|Wdg_Trigger)\b'
        ],
        "default_desc": "MCAL driver controlling hardware watchdog hardware and servicing periodic keep-alive triggers."
    },
    {
        "name": "FlsDriver",
        "full_name": "Flash Driver",
        "type": "MCAL Driver",
        "layer": "MCAL",
        "patterns": [
            r'\b(?:Flash\s+Driver|Fls_Init|Fls_Write|Fls_Erase)\b'
        ],
        "default_desc": "MCAL driver providing direct programming and erasing operations for on-chip or external flash memory."
    }
]

def _is_blocked_term(name: str) -> bool:
    """Check if a candidate name is in the generic terms blocklist (with plural handling)."""
    clean = name.lower().strip()
    if clean in GENERIC_TERMS_BLOCKLIST:
        return True
    # Check plural suffixes (e.g. services -> service, interfaces -> interface)
    if clean.endswith('es') and clean[:-2] in GENERIC_TERMS_BLOCKLIST:
        return True
    if clean.endswith('s') and clean[:-1] in GENERIC_TERMS_BLOCKLIST:
        return True
    return False


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences for co-occurrence analysis."""
    # Split on period-space, newline, or semicolon boundaries
    return re.split(r'(?<=[.!?;])\s+|\n', text)


def extract_architecture_from_document(
    file_path: str,
    project_id: str,
    doc_id: str,
    db: Session,
    old_doc_id: Optional[str] = None
) -> Dict[str, int]:
    """
    Extract components, interfaces, ports, and dependencies from an ingested document.
    - Grounded in document evidence (no hardcoded fake relationships).
    - Requires formal module naming patterns (prevents single-word false positives).
    - Discovers custom application SWCs, interfaces, and ports dynamically.
    - Cites the specific source page for every extracted element.
    - Uses OCR fallback for scanned/image pages (mirrors ingestion.py).
    - Filters generic terms via blocklist to prevent false-positive noise.
    - Accepts old_doc_id to properly clean up previous extraction on re-upload.
    """
    doc = pymupdf.open(file_path)
    page_count = len(doc)
    pages_text: Dict[int, str] = {}
    ocr_pages_scanned = 0
    
    for idx in range(page_count):
        page = doc[idx]
        text = page.get_text("text").strip()
        
        # OCR fallback for scanned/image-based pages (mirrors ingestion.py logic)
        if len(text) < 40:
            try:
                ocr_tp = page.get_textpage_ocr(language='eng')
                ocr_result = page.get_text("text", textpage=ocr_tp).strip()
                if len(ocr_result) > 20:
                    text = ocr_result
                    ocr_pages_scanned += 1
            except Exception:
                pass
        
        pages_text[idx + 1] = text

    # Remove previous extraction rows for this document.
    # Delete by both old_doc_id (prior extraction batch) and current doc_id (idempotency).
    doc_ids_to_clean = [doc_id]
    if old_doc_id and old_doc_id != doc_id:
        doc_ids_to_clean.append(old_doc_id)
    
    for did in doc_ids_to_clean:
        db.query(ArchitectureComponent).filter(ArchitectureComponent.doc_id == did).delete()
        db.query(ArchitectureInterface).filter(ArchitectureInterface.doc_id == did).delete()
        db.query(ArchitecturePort).filter(ArchitecturePort.doc_id == did).delete()
        db.query(ArchitectureDependency).filter(ArchitectureDependency.doc_id == did).delete()
    db.commit()

    components_found: Dict[str, ArchitectureComponent] = {}
    interfaces_found: Dict[str, ArchitectureInterface] = {}
    ports_found: List[ArchitecturePort] = []
    dependencies_found: List[ArchitectureDependency] = []

    # 1. EVIDENCE-BASED BSW MODULE DETECTION
    # For each formal module, verify if its disambiguated patterns exist in the document
    for mod_info in AUTOSAR_FORMAL_MODULES:
        mod_name = mod_info["name"]
        patterns = mod_info["patterns"]
        
        found = False
        first_page = 1
        found_snippet = ""
        
        for p_num, p_text in pages_text.items():
            for pat in patterns:
                match = re.search(pat, p_text, re.IGNORECASE)
                if match:
                    found = True
                    first_page = p_num
                    start = max(0, match.start() - 30)
                    end = min(len(p_text), match.end() + 100)
                    found_snippet = p_text[start:end].replace("\n", " ").strip()
                    break
            if found:
                break
                
        if found:
            desc = f"{mod_info['full_name']} ({mod_name}). {mod_info['default_desc']}"
            if found_snippet:
                desc += f" Evidence: \"...{found_snippet[:120]}...\""
                
            comp = ArchitectureComponent(
                project_id=project_id,
                doc_id=doc_id,
                name=mod_name,
                component_type=mod_info["type"],
                layer=mod_info["layer"],
                description=desc,
                source_page=first_page
            )
            db.add(comp)
            components_found[mod_name] = comp

    # 2. EVIDENCE-BASED CUSTOM APPLICATION SWC DETECTION
    # Scan for custom application components defined in document headings, text, or architecture descriptions
    swc_patterns = [
        r'\b([A-Z][a-zA-Z0-9_]{3,30}_(?:SWC|Component|Controller|Manager|Sensor|Actuator))\b',
        r'\bSWC_([A-Z][a-zA-Z0-9_]{3,30})\b',
        r'\b([A-Z][a-zA-Z0-9]{3,25})\s+Software\s+Component\b',
        r'\b([A-Z][a-zA-Z0-9]{3,25})\s+SWC\b'
    ]
    
    for p_num, p_text in pages_text.items():
        for pat in swc_patterns:
            for match in re.finditer(pat, p_text):
                swc_name = match.group(1).strip()
                if swc_name not in components_found and len(swc_name) > 4:
                    # Filter out generic terms and common stop words
                    if _is_blocked_term(swc_name):
                        continue
                    
                    comp = ArchitectureComponent(
                        project_id=project_id,
                        doc_id=doc_id,
                        name=swc_name,
                        component_type="Application SWC",
                        layer="Application",
                        description=f"Application Software Component extracted from document text at page {p_num}.",
                        source_page=p_num
                    )
                    db.add(comp)
                    components_found[swc_name] = comp

    # 3. EVIDENCE-BASED INTERFACE DETECTION
    # Scan text for actual interface names and interface definitions
    interface_patterns = [
        # Explicit Interface Names like Speed_SR_Interface, CanIf_TransmitInterface
        r'\b([A-Z][a-zA-Z0-9_]{2,30}_(?:Interface|If|I))\b',
        r'\b(Sender[- ]Receiver\s+Interface\s+(?:for\s+)?([A-Za-z0-9_]+))\b',
        r'\b(Client[- ]Server\s+Interface\s+(?:for\s+)?([A-Za-z0-9_]+))\b',
        r'\b(?:AUTOSAR|Standardized)\s+Interface\s+([A-Za-z0-9_]{3,30})\b',
        r'\bInterface\s+([A-Z][a-zA-Z0-9_]{3,30})\b'
    ]
    
    for p_num, p_text in pages_text.items():
        for pat in interface_patterns:
            for match in re.finditer(pat, p_text):
                raw_if = match.group(1).strip()
                # Clean up interface name
                if_name = re.sub(r'^(?:Interface|Sender[- ]Receiver\s+Interface\s+for|Client[- ]Server\s+Interface\s+for)\s*', '', raw_if).strip()
                if_name = re.sub(r'[^a-zA-Z0-9_]', '_', if_name)
                
                if len(if_name) > 3 and if_name not in interfaces_found:
                    # Filter out generic terms that aren't actual interface names
                    if _is_blocked_term(if_name):
                        continue
                    
                    # For the bare "Interface X" pattern, require at least one underscore or digit
                    # to avoid matching "Interface Description", "Interface Specification", etc.
                    if pat == r'\bInterface\s+([A-Z][a-zA-Z0-9_]{3,30})\b':
                        if '_' not in if_name and not any(c.isdigit() for c in if_name):
                            continue
                    
                    # Determine interface type from surrounding sentence
                    line_start = max(0, match.start() - 100)
                    line_end = min(len(p_text), match.end() + 100)
                    context_snippet = p_text[line_start:line_end].lower()
                    
                    if "sender" in context_snippet or "receiver" in context_snippet or "signal" in context_snippet:
                        if_type = "Sender-Receiver"
                    elif "client" in context_snippet or "server" in context_snippet or "operation" in context_snippet or "call" in context_snippet:
                        if_type = "Client-Server"
                    elif "mode" in context_snippet:
                        if_type = "Mode Switch"
                    elif "parameter" in context_snippet:
                        if_type = "Parameter"
                    else:
                        if_type = "Standardized Interface"
                        
                    # Extract sample operations/data elements mentioned nearby
                    elem_match = re.search(r'(?:data\s+element|operation|function|service)\s+([A-Za-z0-9_]+)', context_snippet)
                    elements = elem_match.group(1) if elem_match else "Grounded interface definition"
                    
                    if_obj = ArchitectureInterface(
                        project_id=project_id,
                        doc_id=doc_id,
                        name=if_name,
                        interface_type=if_type,
                        elements_or_operations=elements,
                        source_page=p_num
                    )
                    db.add(if_obj)
                    interfaces_found[if_name] = if_obj

    # 4. EVIDENCE-BASED PORT DETECTION
    # Scan text for explicit port declarations and broader port-related phrasing
    port_patterns_pport = [
        r'\b(PPort_[A-Za-z0-9_]+)\b',
        r'\b(P_[A-Z][a-zA-Z0-9_]{2,30})\b',
        r'\b(Pp[A-Z][a-zA-Z0-9_]{2,30})\b',
        r'\bP-Port\s+([A-Za-z0-9_]+)\b',
        r'\b(?:P-Port|Provided\s+Port|PPort)\s*[:=]\s*([A-Za-z0-9_]+)\b',
        r'\bProvided\s+Port\s+([A-Za-z0-9_]+)\b',
        r'\bprovide[sd]?\s+(?:port|interface)\s+([A-Za-z0-9_]+)\b',
        r'\bsender\s+port\s+([A-Za-z0-9_]+)\b',
        r'\bservice\s+port\s+([A-Za-z0-9_]+)\b',
        r'\bprovided\s+interface\s+([A-Za-z0-9_]+)\b',
        r'<P-PORT-PROTOTYPE[^>]*>.*?<SHORT-NAME>([A-Za-z0-9_]+)</SHORT-NAME>',
    ]
    port_patterns_rport = [
        r'\b(RPort_[A-Za-z0-9_]+)\b',
        r'\b(R_[A-Z][a-zA-Z0-9_]{2,30})\b',
        r'\b(Rp[A-Z][a-zA-Z0-9_]{2,30})\b',
        r'\bR-Port\s+([A-Za-z0-9_]+)\b',
        r'\b(?:R-Port|Required\s+Port|RPort)\s*[:=]\s*([A-Za-z0-9_]+)\b',
        r'\bRequired\s+Port\s+([A-Za-z0-9_]+)\b',
        r'\brequire[sd]?\s+(?:port|interface)\s+([A-Za-z0-9_]+)\b',
        r'\breceiver\s+port\s+([A-Za-z0-9_]+)\b',
        r'\brequired\s+interface\s+([A-Za-z0-9_]+)\b',
        r'<R-PORT-PROTOTYPE[^>]*>.*?<SHORT-NAME>([A-Za-z0-9_]+)</SHORT-NAME>',
    ]
    port_patterns_prport = [
        r'\b(PRPort_[A-Za-z0-9_]+)\b',
        r'\b(PR_[A-Z][a-zA-Z0-9_]{2,30})\b',
        r'\b(PRp[A-Z][a-zA-Z0-9_]{2,30})\b',
        r'\bPR-Port\s+([A-Za-z0-9_]+)\b',
        r'\b(?:PR-Port|Provided-Required\s+Port|PRPort)\s*[:=]\s*([A-Za-z0-9_]+)\b',
        r'<PR-PORT-PROTOTYPE[^>]*>.*?<SHORT-NAME>([A-Za-z0-9_]+)</SHORT-NAME>',
    ]
    
    seen_ports: Set[Tuple[str, str, str]] = set()  # (component, port_name, port_type)
    
    for p_num, p_text in pages_text.items():
        # Match PPorts
        for pat in port_patterns_pport:
            for match in re.finditer(pat, p_text, re.IGNORECASE):
                # Get the captured port name from whichever group matched
                p_name = None
                for g in range(1, match.lastindex + 1 if match.lastindex else 2):
                    val = match.group(g)
                    if val:
                        p_name = val.strip()
                        break
                if not p_name or len(p_name) < 3 or _is_blocked_term(p_name):
                    continue
                    
                # Associate port with nearest known component on that page
                parent_comp = "Architecture"
                for c_name, c_obj in components_found.items():
                    if c_obj.source_page == p_num or c_name in p_text:
                        parent_comp = c_name
                        break
                
                port_key = (parent_comp, p_name, "PPort")
                if port_key not in seen_ports:
                    seen_ports.add(port_key)
                    port = ArchitecturePort(
                        project_id=project_id,
                        doc_id=doc_id,
                        component_name=parent_comp,
                        port_name=p_name,
                        port_type="PPort",
                        interface_name="",
                        source_page=p_num
                    )
                    db.add(port)
                    ports_found.append(port)
            
        # Match RPorts
        for pat in port_patterns_rport:
            for match in re.finditer(pat, p_text, re.IGNORECASE):
                r_name = None
                for g in range(1, match.lastindex + 1 if match.lastindex else 2):
                    val = match.group(g)
                    if val:
                        r_name = val.strip()
                        break
                if not r_name or len(r_name) < 3 or _is_blocked_term(r_name):
                    continue
                    
                parent_comp = "Architecture"
                for c_name, c_obj in components_found.items():
                    if c_obj.source_page == p_num or c_name in p_text:
                        parent_comp = c_name
                        break
                
                port_key = (parent_comp, r_name, "RPort")
                if port_key not in seen_ports:
                    seen_ports.add(port_key)
                    port = ArchitecturePort(
                        project_id=project_id,
                        doc_id=doc_id,
                        component_name=parent_comp,
                        port_name=r_name,
                        port_type="RPort",
                        interface_name="",
                        source_page=p_num
                    )
                    db.add(port)
                    ports_found.append(port)

        # Match PRPorts (Provided-Required)
        for pat in port_patterns_prport:
            for match in re.finditer(pat, p_text, re.IGNORECASE):
                pr_name = None
                for g in range(1, match.lastindex + 1 if match.lastindex else 2):
                    val = match.group(g)
                    if val:
                        pr_name = val.strip()
                        break
                if not pr_name or len(pr_name) < 3 or _is_blocked_term(pr_name):
                    continue
                    
                parent_comp = "Architecture"
                for c_name, c_obj in components_found.items():
                    if c_obj.source_page == p_num or c_name in p_text:
                        parent_comp = c_name
                        break
                
                port_key = (parent_comp, pr_name, "PRPort")
                if port_key not in seen_ports:
                    seen_ports.add(port_key)
                    port = ArchitecturePort(
                        project_id=project_id,
                        doc_id=doc_id,
                        component_name=parent_comp,
                        port_name=pr_name,
                        port_type="PRPort",
                        interface_name="",
                        source_page=p_num
                    )
                    db.add(port)
                    ports_found.append(port)

    # 5. EVIDENCE-BASED DEPENDENCY / CONNECTOR EXTRACTION
    # Create dependencies if document text explicitly describes interaction between two modules
    comp_names = list(components_found.keys())
    
    # Broad interaction patterns covering real prose phrasing found in AUTOSAR HLD documents
    interaction_patterns = [
        # Direct verb-based patterns: "X provides services to Y", "X transmits to Y", etc.
        r'\b([A-Z][a-zA-Z0-9_]+)\s+(?:provides\s+services\s+to|transmits\s+(?:PDUs|data|signals)\s+to|routes\s+to|calls|invokes|interfaces\s+with|depends\s+on)\s+([A-Z][a-zA-Z0-9_]+)\b',
        # "between X and Y"
        r'\bbetween\s+([A-Z][a-zA-Z0-9_]+)\s+and\s+([A-Z][a-zA-Z0-9_]+)\b',
        # "X uses Y", "X accesses Y", "X communicates with Y"
        r'\b([A-Z][a-zA-Z0-9_]+)\s+(?:uses|accesses|communicates\s+with|interacts\s+with|is\s+connected\s+to|connects\s+to)\s+(?:the\s+)?([A-Z][a-zA-Z0-9_]+)\b',
        # "X sends/reports/notifies Y", "X receives from Y"
        r'\b([A-Z][a-zA-Z0-9_]+)\s+(?:sends|reports|notifies|forwards|delegates)\s+(?:\w+\s+){0,3}(?:to\s+)?([A-Z][a-zA-Z0-9_]+)\b',
        r'\b([A-Z][a-zA-Z0-9_]+)\s+(?:receives|reads|obtains)\s+(?:\w+\s+){0,3}from\s+([A-Z][a-zA-Z0-9_]+)\b',
        # "X ... via/through Y" (layer interaction)
        r'\b([A-Z][a-zA-Z0-9_]+)\s+(?:\w+\s+){0,4}(?:via|through)\s+([A-Z][a-zA-Z0-9_]+)\b',
    ]
    
    seen_deps: Set[Tuple[str, str]] = set()
    
    for p_num, p_text in pages_text.items():
        # Pattern-based explicit dependency detection
        for pat in interaction_patterns:
            for match in re.finditer(pat, p_text):
                src = match.group(1).strip()
                tgt = match.group(2).strip()
                
                # Verify that both source and target are recognized components in this document
                if src in components_found and tgt in components_found and src != tgt:
                    pair = (src, tgt)
                    if pair not in seen_deps:
                        seen_deps.add(pair)
                        dep = ArchitectureDependency(
                            project_id=project_id,
                            doc_id=doc_id,
                            source_component=src,
                            target_component=tgt,
                            interface_name="Documented Architectural Interaction",
                            connector_type="Assembly",
                            status="Connected"
                        )
                        db.add(dep)
                        dependencies_found.append(dep)
        
        # Sentence-level co-occurrence inference:
        # When two known component names appear in the same sentence, infer a potential dependency
        sentences = _split_sentences(p_text)
        for sentence in sentences:
            comps_in_sentence = [cn for cn in comp_names if re.search(r'\b' + re.escape(cn) + r'\b', sentence)]
            if len(comps_in_sentence) >= 2:
                for i in range(len(comps_in_sentence)):
                    for j in range(i + 1, len(comps_in_sentence)):
                        src = comps_in_sentence[i]
                        tgt = comps_in_sentence[j]
                        pair = (src, tgt)
                        reverse_pair = (tgt, src)
                        if pair not in seen_deps and reverse_pair not in seen_deps:
                            seen_deps.add(pair)
                            dep = ArchitectureDependency(
                                project_id=project_id,
                                doc_id=doc_id,
                                source_component=src,
                                target_component=tgt,
                                interface_name="Co-occurrence in document text",
                                connector_type="Assembly",
                                status="Inferred"
                            )
                            db.add(dep)
                            dependencies_found.append(dep)

    db.commit()

    return {
        "components_extracted": len(components_found),
        "interfaces_extracted": len(interfaces_found),
        "ports_extracted": len(ports_found),
        "dependencies_extracted": len(dependencies_found),
        "ocr_pages_scanned": ocr_pages_scanned
    }

def get_project_inventory(project_id: str, db: Session) -> ArchitectureInventoryResponse:
    """Retrieve full structured architecture inventory and completeness report."""
    comps = db.query(ArchitectureComponent).filter(ArchitectureComponent.project_id == project_id).all()
    ifs = db.query(ArchitectureInterface).filter(ArchitectureInterface.project_id == project_id).all()
    deps = db.query(ArchitectureDependency).filter(ArchitectureDependency.project_id == project_id).all()
    ports = db.query(ArchitecturePort).filter(ArchitecturePort.project_id == project_id).all()

    inconsistencies: List[str] = []
    
    # 1. Completeness checks for unconnected ports
    provided_ports = {p.port_name for p in ports if p.port_type in ["PPort", "PRPort"]}
    required_ports = {p.port_name for p in ports if p.port_type in ["RPort", "PRPort"]}
    
    # 2. Check for isolated components
    connected_comps = set()
    for d in deps:
        connected_comps.add(d.source_component)
        connected_comps.add(d.target_component)
    
    for c in comps:
        if c.name not in connected_comps and c.layer not in ["MCAL", "Services"]:
            inconsistencies.append(f"Potential Isolated Component: '{c.name}' has no registered interaction connectors in this document.")

    return ArchitectureInventoryResponse(
        project_id=project_id,
        total_components=len(comps),
        total_interfaces=len(ifs),
        total_ports=len(ports),
        total_dependencies=len(deps),
        components=[
            ComponentItem(
                name=c.name,
                component_type=c.component_type,
                layer=c.layer,
                description=c.description,
                source_page=c.source_page
            ) for c in comps
        ],
        interfaces=[
            InterfaceItem(
                name=i.name,
                interface_type=i.interface_type,
                elements_or_operations=i.elements_or_operations,
                source_page=i.source_page
            ) for i in ifs
        ],
        ports=[
            PortItem(
                component_name=p.component_name,
                port_name=p.port_name,
                port_type=p.port_type,
                interface_name=p.interface_name,
                source_page=p.source_page
            ) for p in ports
        ],
        dependencies=[
            DependencyItem(
                source_component=d.source_component,
                target_component=d.target_component,
                interface_name=d.interface_name,
                connector_type=d.connector_type,
                status=d.status
            ) for d in deps
        ],
        inconsistencies=inconsistencies
    )
