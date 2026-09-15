import math
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from app.models import QueryResponse, Citation
from app.database import AuditLog, User
from app.config import settings
from app.services.ingestion import embeddings, get_project_collection_name

# Configurable LLM - Supports any approved model via Ollama (llama3, mistral, qwen, deepseek)
llm = OllamaLLM(
    model=settings.OLLAMA_MODEL,
    base_url=settings.OLLAMA_BASE_URL,
    temperature=settings.LLM_TEMPERATURE
)

system_prompt = (
    "You are an expert AI assistant specialized in AUTOSAR High-Level Design (HLD) Document Analysis. "
    "Analyze the following retrieved architecture evidence to answer the engineering question. "
    "\n\nRules:"
    "\n1. Ground your answer ONLY in the provided architecture context."
    "\n2. If the answer is not supported by the evidence, state clearly that the architecture specification does not contain this information."
    "\n3. Always include precise citations indicating the Document Name, Page Number, and Section when stating facts."
    "\n4. Maintain strict automotive engineering terminology (e.g., SWC, RTE, BSW, MCAL, VFB, PPort, RPort, PDU, Dcm, Dem).\n\n"
    "Context:\n{context}"
)

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{question}"),
])

def format_docs(docs_with_scores: List[Tuple[Any, float]]) -> str:
    formatted = []
    for doc, _ in docs_with_scores:
        meta = doc.metadata
        header = f"[{meta.get('source', 'Unknown')} | Page {meta.get('page', '?')} | Section: {meta.get('section', 'General')}]"
        formatted.append(f"{header}\n{doc.page_content}")
    return "\n\n---\n\n".join(formatted)

def calculate_confidence(docs_with_scores: List[Tuple[Any, float]]) -> Tuple[float, str]:
    """
    Compute heuristic confidence proxy from vector retrieval distance scores.
    
    IMPORTANT ARCHITECTURAL NOTE ON CALIBRATION:
    This score is an uncalibrated linear heuristic (0.10 - 0.98) derived from raw Chroma
    vector similarity distances. It is an indicator of contextual retrieval proximity, NOT
    a calibrated Bayesian or statistical safety probability. For automotive governance
    (ISO 26262, ASPICE), decisions must be backed by traceable human specialist sign-off.
    """
    if not docs_with_scores:
        return 0.0, "LOW"
    scores = [score for _, score in docs_with_scores]
    avg_score = sum(scores) / len(scores)
    confidence = max(0.1, min(0.98, 1.0 - (avg_score / 2.0)))
    if confidence >= 0.75:
        level = "HIGH"
    elif confidence >= 0.50:
        level = "MEDIUM"
    else:
        level = "LOW"
    return round(confidence, 2), level

def query_documents(
    query_text: str,
    project_id: str,
    user: User,
    db: Session
) -> QueryResponse:
    collection_name = get_project_collection_name(project_id)
    vectorstore = Chroma(
        collection_name=collection_name,
        persist_directory=settings.CHROMA_PERSIST_DIR,
        embedding_function=embeddings
    )
    
    docs_with_scores = vectorstore.similarity_search_with_score(
        query=query_text,
        k=5,
        filter={"project_id": project_id}
    )
    
    if not docs_with_scores:
        no_evidence_msg = (
            f"No relevant architectural evidence found in project collection '{project_id}'. "
            "Please ensure relevant AUTOSAR HLD documents are ingested into this program."
        )
        audit = AuditLog(
            username=user.username,
            role=user.role,
            action="QUERY",
            project_id=project_id,
            query_text=query_text,
            response_summary="No evidence found",
            confidence_score=0.0,
            citations_count=0,
            review_status="PENDING_REVIEW"
        )
        db.add(audit)
        db.commit()
        db.refresh(audit)
        
        return QueryResponse(
            answer=no_evidence_msg,
            citations=[],
            confidence_score=0.0,
            confidence_level="LOW",
            limitations=[
                f"No matching chunks found in project collection '{project_id}'.",
                "Queries are isolated to active program boundary."
            ],
            review_status="PENDING_REVIEW",
            audit_id=audit.id,
            project_id=project_id
        )
        
    confidence_score, confidence_level = calculate_confidence(docs_with_scores)
    context_text = format_docs(docs_with_scores)
    
    citations: List[Citation] = []
    seen_pages = set()
    for doc, _ in docs_with_scores:
        meta = doc.metadata
        page = meta.get("page", 1)
        source = meta.get("source", "Document")
        key = (source, page)
        if key not in seen_pages:
            seen_pages.add(key)
            citations.append(Citation(
                source=source,
                page=page,
                section=meta.get("section", "Architecture Specification"),
                snippet=doc.page_content[:240].replace("\n", " ") + "..."
            ))
            
    chain = prompt | llm | StrOutputParser()
    answer = chain.invoke({"context": context_text, "question": query_text})
    
    limitations = [
        f"Grounded exclusively in {len(docs_with_scores)} retrieved sections from project collection '{project_id}'.",
        "Confidence score is an uncalibrated retrieval distance heuristic; not a formal statistical safety probability.",
        "Deterministic architecture governance rules apply: requires expert human review before design release.",
        "External safety/OEM standards beyond the ingested document set were not incorporated."
    ]
    
    audit = AuditLog(
        username=user.username,
        role=user.role,
        action="QUERY",
        project_id=project_id,
        query_text=query_text,
        response_summary=answer[:300] + "...",
        confidence_score=confidence_score,
        citations_count=len(citations),
        review_status="PENDING_REVIEW"
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    
    return QueryResponse(
        answer=answer,
        citations=citations,
        confidence_score=confidence_score,
        confidence_level=confidence_level,
        limitations=limitations,
        review_status="PENDING_REVIEW",
        audit_id=audit.id,
        project_id=project_id
    )
