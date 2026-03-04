"""
GAM-style memory system for SpecTestPilot.

Implements:
- PageStore: Append-only storage for pages (id, title, tags, content, timestamp)
- Memorizer: Produces memos from runs and stores artifacts as pages
- Researcher: Deep-research loop (plan → search → integrate → reflect)

Uses:
- rank_bm25 for keyword search
- sentence-transformers + FAISS for vector search
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Literal
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

from rank_bm25 import BM25Okapi
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    VECTOR_SEARCH_AVAILABLE = False

logger = logging.getLogger(__name__)


# Default conventions for test generation
DEFAULT_CONVENTIONS = [
    {
        "title": "REST API Testing Conventions",
        "tags": ["convention", "rest", "testing"],
        "content": (
            "1. Every endpoint needs at least one happy path test with valid inputs.\n"
            "2. Include negative tests for validation errors (400), auth failures (401/403), "
            "and not found (404).\n"
            "3. Test idempotency for PUT/DELETE operations."
        )
    },
    {
        "title": "Authentication Testing Patterns",
        "tags": ["convention", "auth", "security"],
        "content": (
            "1. Test with valid credentials returns expected response.\n"
            "2. Test with missing auth header returns 401.\n"
            "3. Test with invalid/expired token returns 401 or 403."
        )
    },
    {
        "title": "Request Validation Patterns",
        "tags": ["convention", "validation", "negative"],
        "content": (
            "1. Test missing required fields returns 400 with field name in error.\n"
            "2. Test invalid field types (string vs int) returns 400.\n"
            "3. Test boundary values for numeric fields."
        )
    },
    {
        "title": "Response Schema Validation",
        "tags": ["validator", "schema", "contract"],
        "content": (
            "1. Validate response matches documented schema.\n"
            "2. Check required fields are present.\n"
            "3. Verify data types match specification."
        )
    },
    {
        "title": "Pagination Testing",
        "tags": ["convention", "pagination", "list"],
        "content": (
            "1. Test default pagination returns limited results.\n"
            "2. Test page/offset parameters work correctly.\n"
            "3. Test invalid pagination params return 400."
        )
    }
]


@dataclass
class Session:
    """Represents a GAM session with clear boundaries."""
    session_id: str
    tenant_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    tool_outputs: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_transcript_entry(self, role: str, content: str, timestamp: Optional[float] = None):
        """Add entry to session transcript."""
        self.transcript.append({
            "role": role,
            "content": content,
            "timestamp": timestamp or time.time()
        })
    
    def add_tool_output(self, tool_name: str, output: Any, timestamp: Optional[float] = None):
        """Add tool output to session."""
        self.tool_outputs.append({
            "tool": tool_name,
            "output": output,
            "timestamp": timestamp or time.time()
        })
    
    def add_artifact(self, name: str, content: str, artifact_type: str, timestamp: Optional[float] = None):
        """Add code/log artifact to session."""
        self.artifacts.append({
            "name": name,
            "content": content,
            "type": artifact_type,
            "timestamp": timestamp or time.time()
        })
    
    def end_session(self):
        """Mark session as ended."""
        self.end_time = time.time()
    
    def get_full_content(self) -> str:
        """Get lossless session content for page storage."""
        content_parts = []
        
        # Session metadata
        content_parts.append(f"Session ID: {self.session_id}")
        if self.tenant_id:
            content_parts.append(f"Tenant ID: {self.tenant_id}")
        content_parts.append(f"Duration: {(self.end_time or time.time()) - self.start_time:.2f}s")
        content_parts.append("")
        
        # Transcript
        if self.transcript:
            content_parts.append("=== TRANSCRIPT ===")
            for entry in self.transcript:
                timestamp = datetime.fromtimestamp(entry["timestamp"]).strftime("%H:%M:%S")
                content_parts.append(f"[{timestamp}] {entry['role']}: {entry['content']}")
            content_parts.append("")
        
        # Tool outputs
        if self.tool_outputs:
            content_parts.append("=== TOOL OUTPUTS ===")
            for output in self.tool_outputs:
                timestamp = datetime.fromtimestamp(output["timestamp"]).strftime("%H:%M:%S")
                content_parts.append(f"[{timestamp}] {output['tool']}: {str(output['output'])[:500]}...")
            content_parts.append("")
        
        # Artifacts  
        if self.artifacts:
            content_parts.append("=== ARTIFACTS ===")
            for artifact in self.artifacts:
                timestamp = datetime.fromtimestamp(artifact["timestamp"]).strftime("%H:%M:%S")
                content_parts.append(f"[{timestamp}] {artifact['name']} ({artifact['type']}):")
                content_parts.append(artifact['content'])
                content_parts.append("")
        
        return "\n".join(content_parts)


@dataclass
class Page:
    """A page in the memory store."""
    id: str
    title: str
    tags: List[str]
    content: str
    timestamp: float = field(default_factory=time.time)
    source: Literal["convention", "existing_tests", "runbook", "validator", "memo"] = "memo"
    tenant_id: Optional[str] = None  # Add tenant isolation
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "tags": self.tags,
            "content": self.content,
            "timestamp": self.timestamp,
            "source": self.source,
            "tenant_id": self.tenant_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Page":
        """Create from dictionary."""
        return cls(**data)


class PageStore:
    """
    Append-only storage for memory pages.
    
    Supports both BM25 keyword search and vector similarity search.
    """
    
    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        use_vector_search: bool = True
    ):
        """
        Initialize PageStore.
        
        Args:
            embedding_model: Sentence transformer model name
            use_vector_search: Whether to use vector search (requires sentence-transformers)
        """
        self.pages: List[Page] = []
        self._id_to_idx: Dict[str, int] = {}
        
        # BM25 index
        self._bm25: Optional[BM25Okapi] = None
        self._tokenized_docs: List[List[str]] = []
        
        # Vector search
        self.use_vector_search = use_vector_search and VECTOR_SEARCH_AVAILABLE
        self._embedder: Optional[SentenceTransformer] = None
        self._faiss_index: Optional[Any] = None
        self._embedding_dim: int = 384  # Default for MiniLM
        
        if self.use_vector_search:
            try:
                self._embedder = SentenceTransformer(embedding_model)
                self._embedding_dim = self._embedder.get_sentence_embedding_dimension()
                self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)  # Inner product
            except Exception:
                self.use_vector_search = False
        
        # Static convention seeds are optional. Keep OFF by default so
        # prompt enrichment stays run/spec specific instead of generic/static.
        raw_defaults_mode = str(os.getenv("GAM_STATIC_CONVENTIONS", "off")).strip().lower()
        self._load_static_conventions = raw_defaults_mode in {"1", "true", "yes", "on"}
        if self._load_static_conventions:
            self._load_defaults()
    
    def _load_defaults(self) -> None:
        """Load default convention pages."""
        for conv in DEFAULT_CONVENTIONS:
            self.add_page(
                title=conv["title"],
                tags=conv["tags"],
                content=conv["content"],
                source="convention"
            )
    
    def _generate_id(self, title: str, content: str) -> str:
        """Generate unique page ID."""
        hash_input = f"{title}:{content}:{time.time()}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25."""
        return text.lower().split()
    
    def _rebuild_bm25(self) -> None:
        """Rebuild BM25 index from all pages."""
        self._tokenized_docs = [
            self._tokenize(f"{p.title} {' '.join(p.tags)} {p.content}")
            for p in self.pages
        ]
        if self._tokenized_docs:
            self._bm25 = BM25Okapi(self._tokenized_docs)
        else:
            self._bm25 = None

    def _rebuild_vector_index(self) -> None:
        """Rebuild vector index from all pages."""
        if not self.use_vector_search or self._embedder is None:
            return
        try:
            self._faiss_index = faiss.IndexFlatIP(self._embedding_dim)
            if not self.pages:
                return
            corpus = [
                f"{p.title} {' '.join(p.tags)} {p.content}"
                for p in self.pages
            ]
            embeddings = self._embedder.encode(corpus, normalize_embeddings=True)
            self._faiss_index.add(np.asarray(embeddings, dtype=np.float32))
        except Exception:
            # Fallback to non-vector mode if rebuild fails.
            self.use_vector_search = False
    
    def add_page(
        self,
        title: str,
        tags: List[str],
        content: str,
        source: Literal["convention", "existing_tests", "runbook", "validator", "memo"] = "memo",
        tenant_id: Optional[str] = None
    ) -> Page:
        """
        Add a new page to the store.
        
        Args:
            title: Page title
            tags: List of tags
            content: Page content
            source: Source type
            tenant_id: Tenant ID for isolation
            
        Returns:
            Created Page
        """
        page_id = self._generate_id(title, content)
        page = Page(
            id=page_id,
            title=title,
            tags=tags,
            content=content,
            source=source,
            tenant_id=tenant_id
        )
        
        idx = len(self.pages)
        self.pages.append(page)
        self._id_to_idx[page_id] = idx
        
        # Update BM25
        self._rebuild_bm25()
        
        # Update vector index
        if self.use_vector_search and self._embedder is not None:
            text = f"{title} {' '.join(tags)} {content}"
            embedding = self._embedder.encode([text], normalize_embeddings=True)
            self._faiss_index.add(embedding.astype(np.float32))
        
        return page

    def export_pages(self) -> List[Dict[str, Any]]:
        """Serialize all pages."""
        return [page.to_dict() for page in self.pages]

    def import_pages(self, pages_data: List[Dict[str, Any]], replace: bool = True) -> None:
        """Load pages from serialized payload."""
        if replace:
            self.pages = []
            self._id_to_idx = {}
        for raw in pages_data:
            if not isinstance(raw, dict):
                continue
            try:
                page = Page.from_dict(raw)
            except Exception:
                continue
            if page.id in self._id_to_idx:
                continue
            idx = len(self.pages)
            self.pages.append(page)
            self._id_to_idx[page.id] = idx

        self._rebuild_bm25()
        self._rebuild_vector_index()
    
    def get_page(self, page_id: str) -> Optional[Page]:
        """Get page by ID."""
        idx = self._id_to_idx.get(page_id)
        if idx is not None:
            return self.pages[idx]
        return None
    
    def search_bm25(self, query: str, top_k: int = 5, tenant_id: Optional[str] = None) -> List[Tuple[Page, float]]:
        """
        Search pages using BM25.
        
        Args:
            query: Search query
            top_k: Number of results
            tenant_id: Filter by tenant ID for isolation
            
        Returns:
            List of (Page, score) tuples
        """
        if not self._bm25 or not self.pages:
            return []
        
        tokenized_query = self._tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)
        
        # Get top-k indices
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if not np.isfinite(score):
                continue
            if score == 0.0:
                continue
            page = self.pages[idx]
            # Apply tenant filtering
            if tenant_id is None or page.tenant_id is None or page.tenant_id == tenant_id:
                results.append((page, score))
        
        return results
    
    def search_vector(self, query: str, top_k: int = 5, tenant_id: Optional[str] = None) -> List[Tuple[Page, float]]:
        """
        Search pages using vector similarity.
        
        Args:
            query: Search query
            top_k: Number of results
            tenant_id: Filter by tenant ID for isolation
            
        Returns:
            List of (Page, score) tuples
        """
        if not self.use_vector_search or not self._embedder or not self.pages:
            return []
        
        query_embedding = self._embedder.encode([query], normalize_embeddings=True)
        scores, indices = self._faiss_index.search(
            query_embedding.astype(np.float32), 
            min(top_k, len(self.pages))
        )
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            score_value = float(score)
            if idx < 0 or not np.isfinite(score_value):
                continue
            page = self.pages[idx]
            # Apply tenant filtering
            if tenant_id is None or page.tenant_id is None or page.tenant_id == tenant_id:
                results.append((page, score_value))
        
        return results
    
    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        bm25_weight: float = 0.5,
        tenant_id: Optional[str] = None
    ) -> List[Tuple[Page, float]]:
        """
        Hybrid search combining BM25 and vector search.
        
        Args:
            query: Search query
            top_k: Number of results
            bm25_weight: Weight for BM25 scores (1 - bm25_weight for vector)
            tenant_id: Filter by tenant ID for isolation
            
        Returns:
            List of (Page, score) tuples
        """
        bm25_results = self.search_bm25(query, top_k * 2, tenant_id=tenant_id)
        vector_results = self.search_vector(query, top_k * 2, tenant_id=tenant_id)
        
        # Normalize and combine scores
        page_scores: Dict[str, float] = {}
        
        # Normalize BM25 scores
        if bm25_results:
            bm25_values = [float(s) for _, s in bm25_results]
            min_bm25 = min(bm25_values)
            max_bm25 = max(bm25_values)
            for page, score in bm25_results:
                if max_bm25 == min_bm25:
                    normalized = 1.0
                else:
                    normalized = (float(score) - min_bm25) / (max_bm25 - min_bm25)
                page_scores[page.id] = bm25_weight * normalized
        
        # Normalize and add vector scores
        if vector_results:
            vec_values = [float(s) for _, s in vector_results]
            min_vec = min(vec_values)
            max_vec = max(vec_values)
            for page, score in vector_results:
                if max_vec == min_vec:
                    normalized = 1.0
                else:
                    normalized = (float(score) - min_vec) / (max_vec - min_vec)
                page_scores[page.id] = page_scores.get(page.id, 0) + (1 - bm25_weight) * normalized
        
        # Sort by combined score
        sorted_ids = sorted(page_scores.keys(), key=lambda x: page_scores[x], reverse=True)
        
        results = []
        for page_id in sorted_ids[:top_k]:
            page = self.get_page(page_id)
            if page:
                results.append((page, page_scores[page_id]))
        
        return results
    
    def search_by_tags(
        self, tags: List[str], top_k: int = 5, tenant_id: Optional[str] = None
    ) -> List[Page]:
        """Search pages by tags with optional tenant filtering."""
        tag_set = set(tags)
        scored = []
        for page in self.pages:
            if tenant_id is not None and page.tenant_id not in (None, tenant_id):
                continue
            overlap = len(tag_set & set(page.tags))
            if overlap > 0:
                scored.append((page, overlap))
        
        # Prefer newer pages when tag overlap ties to avoid stale memo reuse.
        scored.sort(
            key=lambda x: (
                x[1],
                float(getattr(x[0], "timestamp", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return [p for p, _ in scored[:top_k]]

    def search_by_page_ids(
        self, page_ids: List[str], tenant_id: Optional[str] = None
    ) -> List[Page]:
        """Retrieve pages by explicit page IDs with optional tenant filtering."""
        seen = set()
        pages: List[Page] = []
        for page_id in page_ids:
            if page_id in seen:
                continue
            seen.add(page_id)
            page = self.get_page(page_id)
            if not page:
                continue
            if tenant_id is not None and page.tenant_id not in (None, tenant_id):
                continue
            pages.append(page)
        return pages


class Memorizer:
    """
    Produces memos from agent runs and stores artifacts as pages.
    Supports session-based lossless storage with contextual headers.
    """
    
    def __init__(self, page_store: PageStore):
        """
        Initialize Memorizer.

        Args:
            page_store: PageStore instance
        """
        self.page_store = page_store
        self._active_sessions: Dict[str, Session] = {}
        raw_memo_mode = (
            str(os.getenv("GAM_MEMO_LLM_MODE", os.getenv("GAM_LLM_MODE", "on")))
            .strip()
            .lower()
            or "on"
        )
        if raw_memo_mode != "on":
            logger.warning(
                "Ignoring GAM_MEMO_LLM_MODE=%s. GAM memo LLM mode is enforced to 'on'.",
                raw_memo_mode,
            )
        self._llm_mode = "on"
        self._llm_model = (
            str(os.getenv("GAM_MEMO_OPENAI_MODEL", os.getenv("GAM_OPENAI_MODEL", "gpt-4.1-mini")))
            .strip()
            or "gpt-4.1-mini"
        )
        self._llm_temperature = self._safe_float(
            os.getenv("GAM_MEMO_LLM_TEMPERATURE", os.getenv("GAM_LLM_TEMPERATURE")),
            default=0.1,
        )
        self._llm_max_tokens = self._safe_int(
            os.getenv("GAM_MEMO_LLM_MAX_TOKENS", os.getenv("GAM_LLM_MAX_TOKENS")),
            default=180,
        )
        self._llm_timeout = self._safe_float(
            os.getenv("GAM_MEMO_LLM_TIMEOUT_SECONDS", os.getenv("GAM_LLM_TIMEOUT_SECONDS")),
            default=10.0,
        )
        self._llm_client = self._init_llm_client()
        self._llm_enabled = self._llm_client is not None

    @staticmethod
    def _safe_float(value: Optional[str], default: float) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _safe_int(value: Optional[str], default: int) -> int:
        try:
            if value is None:
                return int(default)
            return int(value)
        except Exception:
            return int(default)

    def _init_llm_client(self) -> Any:
        if self._llm_mode == "off":
            return None

        api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
        if not api_key:
            if self._llm_mode == "on":
                logger.warning(
                    "GAM_MEMO_LLM_MODE=on but OPENAI_API_KEY is missing. "
                    "Falling back to heuristic contextual memo headers."
                )
            return None

        try:
            from openai import OpenAI

            return OpenAI(api_key=api_key)
        except Exception as exc:
            logger.warning("Failed to initialize OpenAI client for memo contextualization: %s", exc)
            return None

    def _llm_context_suffix(
        self,
        *,
        spec_title: str,
        tenant_id: Optional[str],
        related_titles: List[str],
        base_header: str,
    ) -> str:
        if not self._llm_enabled or self._llm_client is None:
            return ""

        payload = {
            "spec_title": str(spec_title),
            "tenant_id": str(tenant_id or ""),
            "base_header": str(base_header),
            "related_titles": list(related_titles[:5]),
            "instruction": (
                "Return a concise suffix (2-6 words) describing what changed since prior runs. "
                "No punctuation-heavy text."
            ),
        }
        try:
            response = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You generate short run-context suffixes for QA memo titles.\n"
                            "Output STRICT JSON: {\"suffix\":\"...\"}\n"
                            "Rules: plain text only, max 6 words, no markdown."
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
                ],
                temperature=float(self._llm_temperature),
                max_tokens=int(self._llm_max_tokens),
                response_format={"type": "json_object"},
                timeout=float(self._llm_timeout),
            )
            content = ""
            if getattr(response, "choices", None):
                message = getattr(response.choices[0], "message", None)
                content = str(getattr(message, "content", "") or "")
            parsed = json.loads(content) if content else {}
            suffix = " ".join(str((parsed or {}).get("suffix", "")).split()).strip()
            if not suffix:
                return ""
            words = suffix.split()
            if len(words) > 6:
                suffix = " ".join(words[:6])
            return suffix
        except Exception as exc:
            logger.warning("Memo contextual LLM call failed. Using heuristic header only: %s", exc)
            return ""
    
    def start_session(self, tenant_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Start a new GAM session with clear boundaries.
        
        Args:
            tenant_id: Tenant ID for isolation
            metadata: Optional session metadata
            
        Returns:
            Session ID
        """
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            tenant_id=tenant_id,
            metadata=metadata or {}
        )
        self._active_sessions[session_id] = session
        return session_id
    
    def add_to_session(
        self, 
        session_id: str, 
        role: str, 
        content: str, 
        tool_outputs: Optional[List[Dict[str, Any]]] = None,
        artifacts: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Add content to an active session.
        
        Args:
            session_id: Session ID
            role: Role (user, assistant, system, tool)
            content: Content to add
            tool_outputs: Tool outputs to record
            artifacts: Code/log artifacts to record
        """
        if session_id not in self._active_sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._active_sessions[session_id]
        session.add_transcript_entry(role, content)
        
        if tool_outputs:
            for tool_output in tool_outputs:
                session.add_tool_output(tool_output["tool"], tool_output["output"])
        
        if artifacts:
            for artifact in artifacts:
                session.add_artifact(artifact["name"], artifact["content"], artifact["type"])
    
    def end_session_with_memo(
        self,
        session_id: str,
        spec_title: str,
        endpoints_count: int,
        tests_generated: int,
        key_decisions: List[str],
        issues_found: List[str]
    ) -> Tuple[List[Page], Page]:
        """
        End session and create memo with lossless page storage.
        
        Args:
            session_id: Session ID to end
            spec_title: Spec title for memo
            endpoints_count: Number of endpoints processed
            tests_generated: Number of tests generated  
            key_decisions: Key decisions made
            issues_found: Issues discovered
            
        Returns:
            (lossless_pages, memo_page) tuple
        """
        if session_id not in self._active_sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self._active_sessions[session_id]
        session.end_session()
        
        # Create lossless page(s) from session content
        lossless_pages = self._create_session_pages(session, spec_title)
        
        # Create contextual memo with page_id pointers
        memo_page = self._create_contextual_memo(
            session, spec_title, endpoints_count, tests_generated, 
            key_decisions, issues_found, lossless_pages
        )
        
        # Clean up session
        del self._active_sessions[session_id]
        
        return lossless_pages, memo_page
    
    def _create_session_pages(self, session: Session, spec_title: str) -> List[Page]:
        """Create lossless pages from session content with chunking."""
        full_content = session.get_full_content()
        
        # Implement chunking strategy for long sessions (~2048 tokens ≈ 8192 chars)
        MAX_CHUNK_SIZE = 8192
        
        if len(full_content) <= MAX_CHUNK_SIZE:
            # Single page for short sessions
            page = self.page_store.add_page(
                title=f"Session: {spec_title} ({session.session_id[:8]})",
                tags=["session", "lossless", spec_title.lower().replace(" ", "_")],
                content=full_content,
                source="memo",
                tenant_id=session.tenant_id
            )
            return [page]
        else:
            # Multiple pages for long sessions (chunking)
            pages = []
            chunks = self._chunk_content(full_content, MAX_CHUNK_SIZE)
            
            for i, chunk in enumerate(chunks):
                page = self.page_store.add_page(
                    title=f"Session: {spec_title} ({session.session_id[:8]}) - Part {i+1}",
                    tags=["session", "lossless", "chunked", spec_title.lower().replace(" ", "_")],
                    content=chunk,
                    source="memo", 
                    tenant_id=session.tenant_id
                )
                pages.append(page)
            
            return pages
    
    def _chunk_content(self, content: str, max_size: int) -> List[str]:
        """Chunk content intelligently at natural boundaries."""
        if len(content) <= max_size:
            return [content]
        
        chunks = []
        lines = content.split('\n')
        current_chunk = []
        current_size = 0
        
        for line in lines:
            line_size = len(line) + 1  # +1 for newline
            
            if current_size + line_size > max_size and current_chunk:
                # Finish current chunk
                chunks.append('\n'.join(current_chunk))
                current_chunk = [line]
                current_size = line_size
            else:
                current_chunk.append(line)
                current_size += line_size
        
        # Add final chunk
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        return chunks
    
    def _create_contextual_memo(
        self, 
        session: Session, 
        spec_title: str, 
        endpoints_count: int,
        tests_generated: int, 
        key_decisions: List[str],
        issues_found: List[str],
        lossless_pages: List[Page]
    ) -> Page:
        """Create contextual memo using prior memory and page_id pointers."""
        
        # Generate contextual header using prior memory
        contextual_header = self._generate_contextual_header(spec_title, session.tenant_id)
        
        # Build memo content with page_id pointers
        content_parts = [
            f"Context: {contextual_header}",
            f"Spec: {spec_title}",
            f"Endpoints: {endpoints_count}, Tests: {tests_generated}",
        ]
        
        if key_decisions:
            content_parts.append(f"Decisions: {'; '.join(key_decisions[:3])}")
        
        if issues_found:
            content_parts.append(f"Issues: {'; '.join(issues_found[:3])}")
        
        # Add page_id pointers to lossless pages
        if lossless_pages:
            page_refs = [f"page_id:{page.id}" for page in lossless_pages]
            content_parts.append(f"Full session data: {', '.join(page_refs)}")
        
        content = "\n".join(content_parts)
        
        return self.page_store.add_page(
            title=f"{contextual_header}: {spec_title} ({session.session_id[:8]})",
            tags=["memo", "run", "contextual", spec_title.lower().replace(" ", "_")],
            content=content,
            source="memo",
            tenant_id=session.tenant_id
        )
    
    def _generate_contextual_header(self, spec_title: str, tenant_id: Optional[str]) -> str:
        """Generate contextual header using prior memory."""
        # Search for related previous sessions
        related_results = self.page_store.search_bm25(
            spec_title, top_k=3, tenant_id=tenant_id
        )
        prior_runs = [r[0] for r in related_results if "memo" in r[0].tags]

        if len(prior_runs) == 0:
            base_header = "Initial Run"
        elif len(prior_runs) == 1:
            base_header = "Follow-up Analysis"
        elif any("v2" in r.title.lower() or "enhanced" in r.content.lower() for r in prior_runs):
            base_header = "Enhanced Version Analysis"
        else:
            base_header = f"Iteration {len(prior_runs) + 1} Analysis"

        related_titles = [str(page.title) for page in prior_runs[:5] if str(page.title).strip()]
        suffix = self._llm_context_suffix(
            spec_title=spec_title,
            tenant_id=tenant_id,
            related_titles=related_titles,
            base_header=base_header,
        )
        if suffix:
            return f"{base_header}: {suffix}"
        return base_header
    
    def create_memo(
        self,
        run_id: str,
        spec_title: str,
        endpoints_count: int,
        tests_generated: int,
        key_decisions: List[str],
        issues_found: List[str]
    ) -> Page:
        """
        Create a memo summarizing an agent run.
        
        Args:
            run_id: Unique run identifier
            spec_title: Title of the processed spec
            endpoints_count: Number of endpoints detected
            tests_generated: Number of tests generated
            key_decisions: Key decisions made during generation
            issues_found: Issues or missing info found
            
        Returns:
            Created memo Page
        """
        content_parts = [
            f"Spec: {spec_title}",
            f"Endpoints: {endpoints_count}, Tests: {tests_generated}",
        ]
        
        if key_decisions:
            content_parts.append(f"Decisions: {'; '.join(key_decisions[:3])}")
        
        if issues_found:
            content_parts.append(f"Issues: {'; '.join(issues_found[:3])}")
        
        content = "\n".join(content_parts)
        
        return self.page_store.add_page(
            title=f"Run Memo: {spec_title} ({run_id[:8]})",
            tags=["memo", "run", spec_title.lower().replace(" ", "_")],
            content=content,
            source="memo"
        )
    
    def store_artifact(
        self,
        title: str,
        content: str,
        artifact_type: Literal["existing_tests", "runbook", "validator"]
    ) -> Page:
        """
        Store an artifact as a page.
        
        Args:
            title: Artifact title
            content: Artifact content
            artifact_type: Type of artifact
            
        Returns:
            Created Page
        """
        return self.page_store.add_page(
            title=title,
            tags=[artifact_type, "artifact"],
            content=content,
            source=artifact_type
        )


@dataclass
class ResearchResult:
    """Result of a research iteration."""
    plan: List[str]
    memory_excerpts: List[Dict[str, str]]
    reflection: str
    should_continue: bool
    iteration: int
    info_checks: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_trace: List[Dict[str, Any]] = field(default_factory=list)
    research_engine: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InfoCheck:
    """
    Structured reflection output aligned with GAM paper flow.

    `request_status` intentionally mirrors the paper's examples:
    - complete
    - need_more
    """

    analysis: str
    request_status: Literal["complete", "need_more"]
    missing: List[str] = field(default_factory=list)
    next_request: str = ""


class Researcher:
    """
    Deep-research loop: plan → search → integrate → reflect.

    Reflection depth is configurable via `GAM_MAX_REFLECTIONS` (default: 2).
    """

    MAX_REFLECTIONS = 2
    MAX_EXCERPTS = 5
    MAX_EXCERPT_LENGTH = 200  # ~2 lines
    MAX_PLAN_ITEMS = 8
    MAX_LEARNING_HINT_QUERIES = 3
    MIN_UNIQUE_SOURCES_TARGET = 2
    MAX_FOLLOW_UP_REQUESTS = 2
    PAGE_ID_REGEX = re.compile(r"page_id:([a-f0-9]{8,64})", flags=re.IGNORECASE)
    LLM_SYSTEM_PLAN_PROMPT = (
        "You are GAM Planner. Build retrieval queries for QA test-strategy research.\n"
        "Output STRICT JSON with key 'queries': string array.\n"
        "Constraints:\n"
        "- Prefer spec-specific and failure-specific queries over generic advice.\n"
        "- Include query diversity: auth, validation, boundary/error, and domain risks when relevant.\n"
        "- Keep queries concise and directly retrievable from memory pages.\n"
        "- Do not include markdown or prose outside JSON."
    )
    LLM_SYSTEM_REFLECT_PROMPT = (
        "You are GAM InfoCheck evaluator.\n"
        "Given context + retrieved excerpts, decide if research is sufficient.\n"
        "Output STRICT JSON with keys:\n"
        "- analysis: string\n"
        "- request_status: 'complete' or 'need_more'\n"
        "- missing: string array\n"
        "- next_request: string (empty if complete)\n"
        "Rules:\n"
        "- If evidence is generic or misses known weak patterns, choose need_more.\n"
        "- If request_status is need_more, next_request must be concrete and retrieval-friendly.\n"
        "- No markdown; JSON only."
    )
    
    def __init__(self, page_store: PageStore):
        """
        Initialize Researcher.
        
        Args:
            page_store: PageStore instance
        """
        self.page_store = page_store
        self._last_search_summary: Dict[str, Any] = {}
        self._last_plan_mode = "heuristic"
        self._last_reflect_mode = "heuristic"
        self._llm_stats: Dict[str, int] = {
            "plan_calls": 0,
            "plan_success": 0,
            "plan_errors": 0,
            "reflect_calls": 0,
            "reflect_success": 0,
            "reflect_errors": 0,
        }
        raw_llm_mode = str(os.getenv("GAM_LLM_MODE", "on")).strip().lower() or "on"
        if raw_llm_mode != "on":
            logger.warning(
                "Ignoring GAM_LLM_MODE=%s. GAM researcher LLM mode is enforced to 'on'.",
                raw_llm_mode,
            )
        self._llm_mode = "on"
        self._llm_model = str(os.getenv("GAM_OPENAI_MODEL", "gpt-4.1-mini")).strip() or "gpt-4.1-mini"
        self._llm_temperature = self._safe_float(os.getenv("GAM_LLM_TEMPERATURE"), default=0.1)
        self._llm_max_tokens = self._safe_int(os.getenv("GAM_LLM_MAX_TOKENS"), default=700)
        self._llm_timeout = self._safe_float(os.getenv("GAM_LLM_TIMEOUT_SECONDS"), default=12.0)
        self._llm_client = self._init_llm_client()
        self._llm_enabled = self._llm_client is not None
        self._max_reflections = self._resolve_max_reflections()

    @staticmethod
    def _safe_float(value: Optional[str], default: float) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _safe_int(value: Optional[str], default: int) -> int:
        try:
            if value is None:
                return int(default)
            return int(value)
        except Exception:
            return int(default)

    def _resolve_max_reflections(self) -> int:
        raw = os.getenv("GAM_MAX_REFLECTIONS")
        if raw is None:
            return int(self.MAX_REFLECTIONS)
        try:
            value = int(raw)
        except Exception:
            return int(self.MAX_REFLECTIONS)
        # Keep bounded to avoid runaway loops.
        return max(1, min(8, value))

    @staticmethod
    def _compact_json(data: Any) -> str:
        try:
            return json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        except Exception:
            return "{}"

    def _init_llm_client(self) -> Any:
        if self._llm_mode == "off":
            return None

        api_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
        if not api_key:
            if self._llm_mode == "on":
                logger.warning(
                    "GAM_LLM_MODE=on but OPENAI_API_KEY is missing. Falling back to heuristic GAM planner."
                )
            return None

        try:
            from openai import OpenAI

            return OpenAI(api_key=api_key)
        except Exception as exc:
            logger.warning("Failed to initialize OpenAI client for GAM LLM mode: %s", exc)
            return None

    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else None
        except Exception:
            pass

        fence_match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if fence_match:
            try:
                payload = json.loads(fence_match.group(0))
                return payload if isinstance(payload, dict) else None
            except Exception:
                return None
        return None

    def _call_llm_json(self, task: Literal["plan", "reflect"], payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._llm_enabled or self._llm_client is None:
            return None

        call_key = f"{task}_calls"
        success_key = f"{task}_success"
        error_key = f"{task}_errors"
        self._llm_stats[call_key] = int(self._llm_stats.get(call_key, 0)) + 1

        system_prompt = (
            self.LLM_SYSTEM_PLAN_PROMPT
            if task == "plan"
            else self.LLM_SYSTEM_REFLECT_PROMPT
        )
        user_prompt = self._compact_json(payload)
        try:
            response = self._llm_client.chat.completions.create(
                model=self._llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=float(self._llm_temperature),
                max_tokens=int(self._llm_max_tokens),
                response_format={"type": "json_object"},
                timeout=float(self._llm_timeout),
            )
            content = ""
            if getattr(response, "choices", None):
                first_choice = response.choices[0]
                message = getattr(first_choice, "message", None)
                content = str(getattr(message, "content", "") or "")
            parsed = self._extract_json_object(content)
            if isinstance(parsed, dict):
                self._llm_stats[success_key] = int(self._llm_stats.get(success_key, 0)) + 1
                return parsed
            self._llm_stats[error_key] = int(self._llm_stats.get(error_key, 0)) + 1
            return None
        except Exception as exc:
            self._llm_stats[error_key] = int(self._llm_stats.get(error_key, 0)) + 1
            logger.warning("GAM LLM %s call failed. Falling back to heuristic mode: %s", task, exc)
            return None

    def _llm_plan(self, context: Dict[str, Any]) -> List[str]:
        endpoint_preview = []
        for item in list(context.get("endpoints", []) or [])[:8]:
            if not isinstance(item, dict):
                continue
            endpoint_preview.append(
                {
                    "method": str(item.get("method", "")).upper(),
                    "path": str(item.get("path", "")),
                }
            )
        payload = {
            "spec_title": str(context.get("spec_title", "")),
            "auth_type": str(context.get("auth_type", "")),
            "research_iteration": int(context.get("research_iteration", 1) or 1),
            "follow_up_requests": list(context.get("follow_up_requests", []) or [])[: self.MAX_FOLLOW_UP_REQUESTS],
            "learning_weakness_hints": list(context.get("learning_weakness_hints", []) or [])[: self.MAX_LEARNING_HINT_QUERIES],
            "prior_page_ids": list(context.get("prior_page_ids", []) or [])[: self.MAX_EXCERPTS * 2],
            "endpoints": endpoint_preview,
            "max_queries": int(self.MAX_PLAN_ITEMS),
        }
        llm_payload = self._call_llm_json("plan", payload)
        if not isinstance(llm_payload, dict):
            return []

        raw_queries = llm_payload.get("queries", [])
        if isinstance(raw_queries, str):
            raw_queries = [line.strip("- ").strip() for line in raw_queries.splitlines() if str(line).strip()]
        if not isinstance(raw_queries, list):
            return []

        queries: List[str] = []
        seen: set[str] = set()
        for item in raw_queries:
            query = " ".join(str(item or "").strip().split())
            if not query:
                continue
            key = query.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append(query)
            if len(queries) >= self.MAX_PLAN_ITEMS:
                break
        return queries

    def plan(self, context: Dict[str, Any]) -> List[str]:
        """
        Create research plan based on context.
        
        Args:
            context: Dict with spec_title, endpoints, auth_type, etc.
            
        Returns:
            List of plan steps
        """
        llm_queries = self._llm_plan(context)
        heuristic_queries = self._heuristic_plan(context)

        if llm_queries:
            merged: List[str] = []
            seen: set[str] = set()
            for query in llm_queries + heuristic_queries:
                normalized = " ".join(str(query or "").strip().split())
                if not normalized:
                    continue
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(normalized)
                if len(merged) >= self.MAX_PLAN_ITEMS:
                    break
            self._last_plan_mode = "llm_primary"
            return merged

        self._last_plan_mode = "heuristic_fallback"
        return heuristic_queries

    def _heuristic_plan(self, context: Dict[str, Any]) -> List[str]:
        plan: List[str] = []
        seen_queries: set[str] = set()

        def add_query(query: str) -> None:
            normalized = " ".join(str(query).strip().split())
            if not normalized:
                return
            key = normalized.lower()
            if key in seen_queries:
                return
            seen_queries.add(key)
            plan.append(normalized)

        # Auth-specific research
        auth_type = str(context.get("auth_type", "unknown"))
        if auth_type not in ["none", "unknown"]:
            add_query(f"Search for {auth_type} authentication testing patterns")

        # Endpoint-specific research
        endpoints = context.get("endpoints", [])
        methods = {str(e.get("method", "")).upper() for e in endpoints if isinstance(e, dict)}

        if "POST" in methods or "PUT" in methods or "PATCH" in methods:
            add_query("Search for request validation testing patterns")

        if any(
            "list" in str(e.get("path", "")).lower() or str(e.get("path", "")).endswith("s")
            for e in endpoints
            if isinstance(e, dict)
        ):
            add_query("Search for pagination testing patterns")

        spec_title = str(context.get("spec_title", "")).strip()
        if spec_title:
            add_query(f"Search for QA failure patterns in {spec_title} APIs")

        endpoint_tokens = self._extract_endpoint_tokens(endpoints, limit=2)
        for token in endpoint_tokens:
            add_query(f"Search for API test edge cases for {token} endpoints")

        learning_hints = context.get("learning_weakness_hints", [])
        if isinstance(learning_hints, list):
            for hint in learning_hints[: self.MAX_LEARNING_HINT_QUERIES]:
                if not isinstance(hint, dict):
                    continue
                method = str(hint.get("method", "")).upper()
                endpoint = str(hint.get("endpoint", "")).strip()
                test_type = str(hint.get("test_type", "")).strip().replace("_", " ")
                expected_status = hint.get("expected_status")
                if method and endpoint:
                    add_query(
                        f"Search for fixes for failing {method} {endpoint} {test_type} tests "
                        f"expecting {expected_status}"
                    )

        iteration = int(context.get("research_iteration", 1) or 1)
        if iteration > 1:
            add_query("Search for alternative test strategies not covered in earlier excerpts")

        follow_up_requests = context.get("follow_up_requests", [])
        if isinstance(follow_up_requests, list):
            for follow_up in follow_up_requests[: self.MAX_FOLLOW_UP_REQUESTS]:
                add_query(str(follow_up))

        return plan[: self.MAX_PLAN_ITEMS]

    def search(
        self,
        plan: List[str],
        tenant_id: Optional[str] = None,
        prior_page_ids: Optional[List[str]] = None,
        spec_memory_tags: Optional[List[str]] = None,
    ) -> List[Tuple[Page, float]]:
        """
        Execute search based on plan.
        
        Implements retrieval tools over pages:
        - retrieve_by_query: hybrid search per query
        - retrieve_by_group: tag/group-based retrieval
        - retrieve_by_page_ids: explicit prior page references
        
        Retrieval calls are executed in parallel and merged.
        
        Args:
            plan: List of search queries
            tenant_id: Optional tenant scope
            prior_page_ids: Optional page IDs from previous iteration
            spec_memory_tags: Optional spec tags to scope memo retrieval
            
        Returns:
            List of (Page, score) tuples
        """
        all_results: Dict[str, Dict[str, Any]] = {}
        futures: List[Any] = []
        future_meta: Dict[Any, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, min(8, len(plan) + 3))) as executor:
            for query in plan:
                future = executor.submit(self.retrieve_by_query, query, tenant_id)
                futures.append(future)
                future_meta[future] = {"kind": "query", "query": query}
            
            group_tags = self._derive_group_tags(plan)
            if group_tags:
                future = executor.submit(self.retrieve_by_group, group_tags, tenant_id)
                futures.append(future)
                future_meta[future] = {"kind": "group", "tags": group_tags}
            
            if prior_page_ids:
                future = executor.submit(
                    self.retrieve_by_page_ids,
                    prior_page_ids[: self.MAX_EXCERPTS * 2],
                    tenant_id,
                )
                futures.append(future)
                future_meta[future] = {"kind": "prior_ids"}

            explicit_page_ids = self._extract_page_ids_from_plan(plan)
            if explicit_page_ids:
                future = executor.submit(
                    self.retrieve_by_page_ids,
                    explicit_page_ids[: self.MAX_EXCERPTS * 2],
                    tenant_id,
                )
                futures.append(future)
                future_meta[future] = {"kind": "plan_page_ids", "page_ids": explicit_page_ids}
            
            for future in as_completed(futures):
                results = future.result()
                meta = future_meta.get(future, {})
                kind = str(meta.get("kind", "query"))
                for rank, (page, score) in enumerate(results):
                    query_match_bonus = 0.04 * max(0, 3 - rank)
                    kind_bonus = 0.06 if kind == "query" else 0.03
                    boosted_score = float(score) + kind_bonus + query_match_bonus
                    entry = all_results.setdefault(
                        page.id,
                        {
                            "page": page,
                            "score": boosted_score,
                            "hit_count": 0,
                            "kinds": set(),
                        },
                    )
                    entry["score"] = max(float(entry["score"]), boosted_score)
                    entry["hit_count"] = int(entry["hit_count"]) + 1
                    kinds = entry.get("kinds")
                    if isinstance(kinds, set):
                        kinds.add(kind)
                    else:
                        entry["kinds"] = {kind}

        raw_results_count = len(all_results)
        all_results = self._filter_results_by_spec_memory_tags(
            all_results,
            spec_memory_tags=spec_memory_tags,
        )
        reranked = self._rerank_with_diversity(
            all_results,
            prior_page_ids=prior_page_ids,
        )
        kind_counts: Dict[str, int] = {}
        for meta in future_meta.values():
            kind = str(meta.get("kind", "query"))
            kind_counts[kind] = int(kind_counts.get(kind, 0)) + 1
        self._last_search_summary = {
            "plan_items": len(plan),
            "futures_by_kind": kind_counts,
            "results_before_filter": raw_results_count,
            "results_after_filter": len(all_results),
            "spec_memory_tags": list(spec_memory_tags or []),
            "explicit_page_ids_used": self._extract_page_ids_from_plan(plan),
            "reranked_count": len(reranked),
        }
        return reranked[: self.MAX_EXCERPTS * 2]

    def _extract_page_ids_from_plan(self, plan: List[str]) -> List[str]:
        page_ids: List[str] = []
        seen: set[str] = set()
        for item in plan:
            text = str(item or "")
            for match in self.PAGE_ID_REGEX.findall(text):
                page_id = str(match).strip()
                if not page_id or page_id in seen:
                    continue
                seen.add(page_id)
                page_ids.append(page_id)
        return page_ids

    def _filter_results_by_spec_memory_tags(
        self,
        all_results: Dict[str, Dict[str, Any]],
        spec_memory_tags: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        required_tags = {
            str(tag).strip().lower() for tag in (spec_memory_tags or []) if str(tag).strip()
        }
        if not required_tags:
            return all_results

        filtered: Dict[str, Dict[str, Any]] = {}
        non_memo_entries: Dict[str, Dict[str, Any]] = {}
        non_memo_non_convention_entries: Dict[str, Dict[str, Any]] = {}
        for page_id, entry in all_results.items():
            page = entry.get("page")
            if not isinstance(page, Page):
                continue

            source = str(page.source or "").strip().lower()
            if source != "memo":
                non_memo_entries[page_id] = entry
                if source != "convention":
                    non_memo_non_convention_entries[page_id] = entry
                continue

            page_tags = {str(tag).strip().lower() for tag in list(page.tags or []) if str(tag).strip()}
            if page_tags.intersection(required_tags):
                filtered[page_id] = entry

        if filtered:
            # Prefer dynamic/spec-specific signals when available.
            if non_memo_non_convention_entries:
                combined = dict(filtered)
                combined.update(non_memo_non_convention_entries)
                return combined
            return filtered

        # No spec-scoped memo evidence found; avoid convention-only fallback unless nothing else exists.
        if non_memo_non_convention_entries:
            return non_memo_non_convention_entries
        if non_memo_entries:
            return non_memo_entries
        return all_results

    def retrieve_by_query(
        self, query: str, tenant_id: Optional[str] = None
    ) -> List[Tuple[Page, float]]:
        """Tool: retrieve pages by free-text query."""
        return self.page_store.hybrid_search(
            query, top_k=self.MAX_EXCERPTS * 2, tenant_id=tenant_id
        )

    def retrieve_by_group(
        self, group_tags: List[str], tenant_id: Optional[str] = None
    ) -> List[Tuple[Page, float]]:
        """Tool: retrieve pages by semantic group tags."""
        pages = self.page_store.search_by_tags(
            group_tags, top_k=self.MAX_EXCERPTS * 2, tenant_id=tenant_id
        )
        # Tag retrieval has weaker evidence than exact query matches.
        return [(page, 0.35 - idx * 0.02) for idx, page in enumerate(pages)]

    def retrieve_by_page_ids(
        self, page_ids: List[str], tenant_id: Optional[str] = None
    ) -> List[Tuple[Page, float]]:
        """Tool: retrieve previously known page IDs."""
        pages = self.page_store.search_by_page_ids(page_ids, tenant_id=tenant_id)
        # Direct page-id retrieval is high-confidence.
        return [(page, 0.60 - idx * 0.03) for idx, page in enumerate(pages)]

    def _derive_group_tags(self, plan: List[str]) -> List[str]:
        """Infer group tags from plan items."""
        tags = set()
        plan_text = " ".join(plan).lower()

        mapping = {
            "auth": ["auth", "security"],
            "security": ["security", "auth"],
            "validation": ["validation", "negative"],
            "schema": ["schema", "contract", "validator"],
            "pagination": ["pagination", "list"],
            "rest": ["rest", "testing", "spec_context"],
            "failure": ["learning", "weakness", "memo"],
            "failing": ["learning", "weakness", "memo"],
            "weak": ["learning", "weakness", "memo"],
            "fixes": ["learning", "weakness", "memo"],
            "edge cases": ["spec_context", "dynamic", "memo"],
        }

        for token, mapped in mapping.items():
            if token in plan_text:
                tags.update(mapped)

        if not tags:
            tags.update({"memo", "spec_context", "learning"})

        return list(tags)

    def _rerank_with_diversity(
        self,
        all_results: Dict[str, Dict[str, Any]],
        prior_page_ids: Optional[List[str]] = None,
    ) -> List[Tuple[Page, float]]:
        prior_set = set(prior_page_ids or [])
        page_timestamps: List[float] = []
        for entry in all_results.values():
            page = entry.get("page")
            if isinstance(page, Page):
                page_timestamps.append(float(getattr(page, "timestamp", 0.0) or 0.0))
        max_timestamp = max(page_timestamps) if page_timestamps else 0.0
        min_timestamp = min(page_timestamps) if page_timestamps else 0.0
        timestamp_span = max(1.0, max_timestamp - min_timestamp)

        candidates: List[Dict[str, Any]] = []
        for page_id, entry in all_results.items():
            page = entry.get("page")
            if not isinstance(page, Page):
                continue
            base_score = float(entry.get("score", 0.0))
            hit_count = int(entry.get("hit_count", 1))
            tag_set = {str(tag).lower() for tag in list(page.tags or [])}
            source_bonus = 0.14 if page.source != "convention" else 0.0
            memo_bonus = 0.06 if page.source == "memo" else 0.0
            contextual_bonus = 0.10 if ("contextual" in tag_set and page.source == "memo") else 0.0
            learning_bonus = 0.40 if ("rl_signal" in tag_set or "learning" in tag_set) else 0.0
            spec_context_bonus = 0.32 if ("spec_context" in tag_set or "run_aware" in tag_set) else 0.0
            page_timestamp = float(getattr(page, "timestamp", 0.0) or 0.0)
            recency_ratio = (
                (page_timestamp - min_timestamp) / timestamp_span
                if max_timestamp > 0.0
                else 0.0
            )
            dynamic_tagged = bool(
                "rl_signal" in tag_set or "spec_context" in tag_set or "run_aware" in tag_set
            )
            recency_bonus = 0.0
            if page.source == "memo":
                recency_bonus = 0.08 * recency_ratio
                if dynamic_tagged:
                    recency_bonus = 0.55 * recency_ratio
            lossless_penalty = 0.24 if ("lossless" in tag_set or "session" in tag_set) else 0.0
            low_signal_penalty = self._low_signal_page_penalty(page)
            hit_bonus = min(0.16, 0.04 * max(0, hit_count - 1))
            prior_penalty = 0.22 if page_id in prior_set else 0.0
            candidates.append(
                {
                    "page": page,
                    "score": (
                        base_score
                        + source_bonus
                        + memo_bonus
                        + contextual_bonus
                        + learning_bonus
                        + spec_context_bonus
                        + recency_bonus
                        + hit_bonus
                        - prior_penalty
                        - lossless_penalty
                        - low_signal_penalty
                    ),
                    "title_sig": self._title_signature(page.title),
                }
            )

        selected: List[Tuple[Page, float]] = []
        source_counts: Dict[str, int] = {}
        title_counts: Dict[str, int] = {}
        remaining = list(candidates)
        while remaining and len(selected) < (self.MAX_EXCERPTS * 2):
            best_idx = 0
            best_score = -1e9
            for idx, item in enumerate(remaining):
                page = item["page"]
                source = str(page.source)
                title_sig = str(item["title_sig"])
                dynamic_score = float(item["score"])
                dynamic_score -= 0.10 * float(source_counts.get(source, 0))
                dynamic_score -= 0.06 * float(title_counts.get(title_sig, 0))
                if dynamic_score > best_score:
                    best_idx = idx
                    best_score = dynamic_score
            chosen = remaining.pop(best_idx)
            chosen_page = chosen["page"]
            selected.append((chosen_page, float(best_score)))
            source_key = str(chosen_page.source)
            source_counts[source_key] = int(source_counts.get(source_key, 0)) + 1
            title_key = str(chosen["title_sig"])
            title_counts[title_key] = int(title_counts.get(title_key, 0)) + 1

        return selected

    def _title_signature(self, title: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()
        tokens = [tok for tok in normalized.split() if tok]
        return " ".join(tokens[:4]) if tokens else "untitled"

    def _low_signal_page_penalty(self, page: Page) -> float:
        if page.source != "memo":
            return 0.0
        tag_set = {str(tag).lower() for tag in list(page.tags or [])}
        if "rl_signal" in tag_set or "spec_context" in tag_set or "run_aware" in tag_set:
            return 0.0
        lower = str(page.content or "").lower()
        penalty = 0.0
        if "training executed" in lower:
            penalty += 0.70
        if "endpoints: 1, tests: 1" in lower:
            penalty += 0.35
        if (
            "context:" in lower
            and "issues:" not in lower
            and "failure" not in lower
            and "failing" not in lower
            and "expected" not in lower
        ):
            penalty += 0.25
        if len(str(page.content or "").strip()) < 100:
            penalty += 0.15
        return penalty

    def _extract_endpoint_tokens(
        self, endpoints: List[Dict[str, Any]], limit: int = 2
    ) -> List[str]:
        stop_words = {"api", "v1", "v2", "id", "by", "with", "and", "or"}
        counts: Dict[str, int] = {}
        for endpoint in endpoints:
            if not isinstance(endpoint, dict):
                continue
            path = str(endpoint.get("path", ""))
            for segment in path.strip("/").split("/"):
                seg = segment.strip().lower()
                if not seg or seg.startswith("{") or seg.endswith("}"):
                    continue
                seg = re.sub(r"[^a-z0-9_\\-]", "", seg)
                if not seg or seg in stop_words:
                    continue
                counts[seg] = int(counts.get(seg, 0)) + 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        return [token for token, _ in ranked[: max(0, int(limit))]]
    
    def integrate(
        self,
        search_results: List[Tuple[Page, float]],
        previous_excerpts: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, str]]:
        """
        Integrate search results into memory excerpts.
        
        Args:
            search_results: List of (Page, score) tuples
            previous_excerpts: Prior integrated excerpts from earlier iteration
            
        Returns:
            List of memory excerpt dicts
        """
        excerpts: List[Dict[str, Any]] = []
        excerpt_signatures: set[str] = set()
        source_seen: set[str] = set()
        previous_signatures = self._collect_excerpt_signatures(previous_excerpts)
        candidates_all = search_results[: self.MAX_EXCERPTS * 2]
        candidates_filtered = [
            item for item in candidates_all if not self._is_lossless_page(item[0])
        ]
        candidates = candidates_filtered if candidates_filtered else candidates_all

        # First pass: ensure source diversity
        for page, score in candidates:
            if len(excerpts) >= self.MAX_EXCERPTS:
                break
            if str(page.source) in source_seen:
                continue
            snippet = self._truncate_excerpt(page)
            if self._is_low_signal_excerpt(snippet, page):
                continue
            snippet_signature = self._excerpt_signature(snippet)
            if (
                snippet_signature
                and snippet_signature in previous_signatures
                and str(page.source) == "memo"
            ):
                # Favor new evidence on later iterations, but keep conventions available.
                continue
            if not self._accept_excerpt(snippet, excerpt_signatures):
                continue
            source_seen.add(str(page.source))
            excerpts.append(self._build_excerpt_payload(page, snippet, score))

        # Second pass: fill remaining slots with novel excerpts
        for page, score in candidates:
            if len(excerpts) >= self.MAX_EXCERPTS:
                break
            snippet = self._truncate_excerpt(page)
            if self._is_low_signal_excerpt(snippet, page):
                continue
            if not self._accept_excerpt(snippet, excerpt_signatures):
                continue
            excerpts.append(self._build_excerpt_payload(page, snippet, score))

        if not excerpts and previous_excerpts:
            # Safety fallback: reuse previous excerpts if strict novelty filtering prunes all.
            for item in previous_excerpts[: self.MAX_EXCERPTS]:
                if isinstance(item, dict):
                    excerpts.append(dict(item))
                    if len(excerpts) >= self.MAX_EXCERPTS:
                        break

        return excerpts

    def _collect_excerpt_signatures(
        self,
        excerpts: Optional[List[Dict[str, Any]]],
    ) -> set[str]:
        signatures: set[str] = set()
        if not isinstance(excerpts, list):
            return signatures
        for excerpt in excerpts:
            if not isinstance(excerpt, dict):
                continue
            signature = self._excerpt_signature(str(excerpt.get("excerpt", "")))
            if signature:
                signatures.add(signature)
        return signatures

    def _is_lossless_page(self, page: Page) -> bool:
        tag_set = {str(tag).lower() for tag in list(page.tags or [])}
        return bool(
            page.source == "memo"
            and (
                "lossless" in tag_set
                or "session" in tag_set
                or "chunked" in tag_set
            )
        )

    def _is_low_signal_excerpt(self, text: str, page: Page) -> bool:
        snippet = str(text or "").strip()
        if not snippet:
            return True
        tag_set = {str(tag).lower() for tag in list(page.tags or [])}
        if "rl_signal" in tag_set or "spec_context" in tag_set or "run_aware" in tag_set:
            return False
        if self._looks_like_json_blob(snippet):
            return True
        lower = snippet.lower()
        if "training executed" in lower:
            return True
        if page.source == "memo":
            if len(snippet) < 50:
                return True
            if (
                lower.startswith("context:")
                and all(
                    token not in lower
                    for token in (
                        "issue",
                        "failure",
                        "failing",
                        "expected",
                        "status",
                        "auth",
                        "validation",
                        "boundary",
                        "pagination",
                        "schema",
                        "endpoint",
                        "error",
                    )
                )
            ):
                return True
        return False

    def _looks_like_json_blob(self, text: str) -> bool:
        raw = str(text).strip()
        if not raw:
            return False
        if (raw.startswith("{") and raw.endswith("}")) or (
            raw.startswith("[") and raw.endswith("]")
        ):
            return True
        if '"total_scenarios"' in raw and '"pass_rate"' in raw:
            return True
        if "'total_scenarios'" in raw and "'pass_rate'" in raw:
            return True
        if raw.count("{") >= 1 and raw.count(":") >= 4 and raw.count(",") >= 4:
            return True
        return False

    def _truncate_excerpt(self, page: Page) -> str:
        text = str(page.content or "").strip()
        tag_set = {str(tag).lower() for tag in list(page.tags or [])}
        if page.source == "memo" and (
            "trend" in tag_set or "rl_signal" in tag_set or "run_aware" in tag_set
        ):
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            spec_line = next(
                (ln for ln in lines if ln.lower().startswith("spec:")),
                "",
            )
            run_line = next(
                (ln for ln in lines if ln.lower().startswith("historical run_count:")),
                "",
            )
            reward_line = next(
                (
                    ln
                    for ln in lines
                    if "last_run_reward=" in ln.lower()
                    or "reward_delta_vs_prev=" in ln.lower()
                ),
                "",
            )
            pattern_line = next(
                (
                    ln
                    for ln in lines
                    if re.match(r"^-\s*(GET|POST|PUT|PATCH|DELETE)\s+", ln, flags=re.IGNORECASE)
                ),
                "",
            )
            parts = [part for part in [pattern_line, reward_line, run_line, spec_line] if part]
            if parts:
                text = " | ".join(parts)
        if page.source == "memo" and ("lossless" in tag_set or "session" in tag_set):
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            filtered: List[str] = []
            for line in lines:
                lower = line.lower()
                if lower.startswith("session id:"):
                    continue
                if lower.startswith("tenant id:"):
                    continue
                if lower.startswith("duration:"):
                    continue
                if lower.startswith("==="):
                    continue
                if re.match(r"^\[[0-9]{2}:[0-9]{2}:[0-9]{2}\]", line):
                    continue
                if lower.endswith("(json):"):
                    continue
                if "qa_agent.execution" in lower or "learning_feedback" in lower:
                    continue
                if self._looks_like_json_blob(line):
                    continue
                filtered.append(line)
            if filtered:
                text = " ".join(filtered[:3])
        elif self._looks_like_json_blob(text):
            text = ""
        if text:
            text = re.sub(r"Full session data:\s*page_id:[^,\s]+(?:,\s*page_id:[^,\s]+)*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"Full session data:\s*[^\n]+", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s+", " ", text).strip()
        if len(text) > self.MAX_EXCERPT_LENGTH:
            return text[: self.MAX_EXCERPT_LENGTH] + "..."
        return text

    def _excerpt_signature(self, text: str) -> str:
        normalized = re.sub(r"\\s+", " ", str(text).strip().lower())
        normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
        tokens = [tok for tok in normalized.split(" ") if tok]
        return " ".join(tokens[:24])

    def _accept_excerpt(self, text: str, seen_signatures: set[str]) -> bool:
        signature = self._excerpt_signature(text)
        if not signature:
            return False
        if signature in seen_signatures:
            return False
        seen_tokens = [set(sig.split()) for sig in seen_signatures if sig]
        candidate_tokens = set(signature.split())
        for token_set in seen_tokens:
            union = candidate_tokens | token_set
            if not union:
                continue
            overlap = len(candidate_tokens & token_set) / len(union)
            if overlap >= 0.80:
                return False
        seen_signatures.add(signature)
        return True

    def _build_excerpt_payload(self, page: Page, snippet: str, score: float) -> Dict[str, Any]:
        return {
            "source": page.source,
            "title": page.title,
            "tags": list(page.tags or []),
            "similarity": round(float(score), 4),
            "excerpt": snippet,
        }
    
    def reflect(
        self,
        context: Dict[str, Any],
        excerpts: List[Dict[str, str]],
        iteration: int,
    ) -> InfoCheck:
        """Reflect on research quality and decide if another iteration is needed."""
        llm_info_check = self._llm_reflect(context=context, excerpts=excerpts, iteration=iteration)
        if isinstance(llm_info_check, InfoCheck):
            self._last_reflect_mode = "llm_primary"
            return llm_info_check
        self._last_reflect_mode = "heuristic_fallback"
        return self._heuristic_reflect(context=context, excerpts=excerpts, iteration=iteration)

    def _llm_reflect(
        self,
        context: Dict[str, Any],
        excerpts: List[Dict[str, str]],
        iteration: int,
    ) -> Optional[InfoCheck]:
        if iteration >= self._max_reflections:
            return InfoCheck(
                analysis=(
                    f"Completed {iteration} research iterations. "
                    f"Found {len(excerpts)} relevant excerpts."
                ),
                request_status="complete",
                missing=[],
                next_request="",
            )
        if not self._llm_enabled:
            return None

        excerpt_payload: List[Dict[str, Any]] = []
        for item in excerpts[:8]:
            if not isinstance(item, dict):
                continue
            excerpt_payload.append(
                {
                    "source": str(item.get("source", "")),
                    "title": str(item.get("title", "")),
                    "tags": list(item.get("tags", [])) if isinstance(item.get("tags"), list) else [],
                    "excerpt": str(item.get("excerpt", ""))[:260],
                }
            )

        payload = {
            "spec_title": str(context.get("spec_title", "")),
            "auth_type": str(context.get("auth_type", "")),
            "research_iteration": int(iteration),
            "max_reflections": int(self._max_reflections),
            "learning_weakness_hints": list(context.get("learning_weakness_hints", []) or [])[: self.MAX_LEARNING_HINT_QUERIES],
            "follow_up_requests": list(context.get("follow_up_requests", []) or [])[: self.MAX_FOLLOW_UP_REQUESTS],
            "endpoints": list(context.get("endpoints", []) or [])[:8],
            "excerpt_count": len(excerpts),
            "excerpts": excerpt_payload,
        }
        llm_payload = self._call_llm_json("reflect", payload)
        if not isinstance(llm_payload, dict):
            return None

        raw_status = str(llm_payload.get("request_status", "")).strip().lower()
        request_status: Literal["complete", "need_more"]
        if raw_status == "need_more":
            request_status = "need_more"
        else:
            request_status = "complete"

        missing_raw = llm_payload.get("missing", [])
        missing: List[str]
        if isinstance(missing_raw, list):
            missing = [
                " ".join(str(item).strip().split())
                for item in missing_raw
                if str(item).strip()
            ][:8]
        else:
            missing = []

        analysis = " ".join(str(llm_payload.get("analysis", "")).strip().split())
        if not analysis:
            analysis = f"Iteration {iteration}: evaluated {len(excerpts)} excerpts."

        next_request = " ".join(str(llm_payload.get("next_request", "")).strip().split())
        if request_status == "need_more" and not next_request:
            next_request = self._build_follow_up_request(
                context=context,
                missing=missing or ["additional evidence"],
                excerpts=excerpts,
                iteration=iteration,
            )
        if request_status == "complete":
            missing = []
            next_request = ""

        return InfoCheck(
            analysis=analysis,
            request_status=request_status,
            missing=missing,
            next_request=next_request,
        )

    def _heuristic_reflect(
        self,
        context: Dict[str, Any],
        excerpts: List[Dict[str, str]],
        iteration: int,
    ) -> InfoCheck:
        if iteration >= self._max_reflections:
            return InfoCheck(
                analysis=(
                    f"Completed {iteration} research iterations. "
                    f"Found {len(excerpts)} relevant excerpts covering spec and learning patterns."
                ),
                request_status="complete",
            )

        # Check coverage
        sources = set(str(e.get("source", "unknown")) for e in excerpts if isinstance(e, dict))
        missing = []

        auth_type = context.get("auth_type", "unknown")
        if auth_type not in ["none", "unknown"] and not any(
            "auth" in str(e.get("excerpt", "")).lower()
            for e in excerpts
            if isinstance(e, dict)
        ):
            missing.append("auth testing patterns")

        unique_sources = len(sources)
        tenant_id = context.get("tenant_id")
        if (
            unique_sources < self.MIN_UNIQUE_SOURCES_TARGET
            and iteration < self._max_reflections
            and self._has_alternative_sources(tenant_id=tenant_id, excluded_sources=sources)
        ):
            missing.append("source diversity")

        learning_hints = context.get("learning_weakness_hints", [])
        if isinstance(learning_hints, list) and learning_hints and iteration < self._max_reflections:
            excerpt_blob = " ".join(str(e.get("excerpt", "")).lower() for e in excerpts)
            hint_missing = 0
            for hint in learning_hints[: self.MAX_LEARNING_HINT_QUERIES]:
                if not isinstance(hint, dict):
                    continue
                endpoint = str(hint.get("endpoint", "")).lower()
                method = str(hint.get("method", "")).lower()
                if endpoint and endpoint.lower() not in excerpt_blob and method and method not in excerpt_blob:
                    hint_missing += 1
            if hint_missing > 0:
                missing.append("historical weakness coverage")

        next_request = ""
        if missing and iteration < self._max_reflections:
            next_request = self._build_follow_up_request(
                context=context,
                missing=missing,
                excerpts=excerpts,
                iteration=iteration,
            )

        if missing and iteration < self._max_reflections:
            return InfoCheck(
                analysis=(
                    f"Iteration {iteration}: Found {len(excerpts)} excerpts. "
                    f"Missing coverage for: {', '.join(missing)}. Continuing research."
                ),
                request_status="need_more",
                missing=missing,
                next_request=next_request,
            )

        return InfoCheck(
            analysis=(
                f"Research complete after {iteration} iteration(s). "
                f"Found {len(excerpts)} relevant excerpts from {len(sources)} sources."
            ),
            request_status="complete",
            missing=[],
            next_request="",
        )

    def _build_follow_up_request(
        self,
        context: Dict[str, Any],
        missing: List[str],
        excerpts: List[Dict[str, str]],
        iteration: int,
    ) -> str:
        spec_title = str(context.get("spec_title", "")).strip() or "this API"
        endpoints = context.get("endpoints", [])
        endpoint_preview = ", ".join(
            f"{str(item.get('method', '')).upper()} {str(item.get('path', '')).strip()}"
            for item in endpoints[:3]
            if isinstance(item, dict)
        )
        missing_blob = ", ".join(str(item) for item in missing[:3])
        if "historical weakness coverage" in missing:
            hints = context.get("learning_weakness_hints", [])
            if isinstance(hints, list):
                for hint in hints[:2]:
                    if not isinstance(hint, dict):
                        continue
                    method = str(hint.get("method", "")).upper()
                    endpoint = str(hint.get("endpoint", "")).strip()
                    expected = str(hint.get("expected_status", ""))
                    if method and endpoint:
                        return (
                            f"Search for actionable failure diagnostics for {method} {endpoint} "
                            f"in {spec_title}, especially expected status {expected} mismatches."
                        )
        if endpoint_preview:
            return (
                f"Search for concrete negative-test patterns for {spec_title} endpoints "
                f"({endpoint_preview}) to close gaps in: {missing_blob}."
            )
        excerpt_titles = ", ".join(
            str(item.get("title", "")).strip()
            for item in excerpts[:2]
            if isinstance(item, dict)
        )
        if excerpt_titles:
            return (
                f"Search for complementary sources beyond [{excerpt_titles}] to address "
                f"{missing_blob} for {spec_title} (iteration {iteration + 1})."
            )
        return (
            f"Search for additional guidance to cover {missing_blob} in {spec_title} "
            f"(iteration {iteration + 1})."
        )

    def _has_alternative_sources(
        self,
        tenant_id: Optional[str],
        excluded_sources: set[str],
    ) -> bool:
        for page in self.page_store.pages:
            if tenant_id is not None and page.tenant_id not in (None, tenant_id):
                continue
            if str(page.source) not in excluded_sources:
                return True
        return False
    
    def research(self, context: Dict[str, Any]) -> ResearchResult:
        """
        Execute full research loop.
        
        Args:
            context: Dict with spec_title, endpoints, auth_type, etc.
            
        Returns:
            ResearchResult with plan, excerpts, and reflection
        """
        all_excerpts: List[Dict[str, Any]] = []
        all_plan: List[str] = []
        info_checks: List[Dict[str, Any]] = []
        retrieval_trace: List[Dict[str, Any]] = []
        iteration_modes: List[Dict[str, Any]] = []
        follow_up_requests: List[str] = []
        seed_page_ids = context.get("prior_page_ids")
        tracked_page_ids: List[str] = (
            [str(item) for item in seed_page_ids if str(item).strip()]
            if isinstance(seed_page_ids, list)
            else []
        )
        seen_excerpt_signatures: set[str] = set()
        tenant_id = context.get("tenant_id")
        
        for iteration in range(1, self._max_reflections + 1):
            loop_context = dict(context)
            loop_context["research_iteration"] = iteration
            loop_context["prior_page_ids"] = list(tracked_page_ids)
            loop_context["follow_up_requests"] = list(
                follow_up_requests[-self.MAX_FOLLOW_UP_REQUESTS :]
            )

            # Plan
            plan = self.plan(loop_context)
            plan_mode = str(self._last_plan_mode)
            all_plan.extend(plan)
            
            # Search
            results = self.search(
                plan,
                tenant_id=tenant_id,
                prior_page_ids=tracked_page_ids,
                spec_memory_tags=context.get("spec_memory_tags"),
            )
            tracked_page_ids = [page.id for page, _ in results]
            retrieval_trace.append(
                {
                    "iteration": iteration,
                    "plan": list(plan),
                    "plan_mode": plan_mode,
                    "search_summary": dict(self._last_search_summary),
                }
            )
            
            # Integrate
            excerpts = self.integrate(results, previous_excerpts=all_excerpts)
            
            # Deduplicate excerpts
            for exc in excerpts:
                signature = self._excerpt_signature(str(exc.get("excerpt", "")))
                if signature and signature not in seen_excerpt_signatures:
                    seen_excerpt_signatures.add(signature)
                    all_excerpts.append(exc)
            
            # Reflect
            info_check = self.reflect(loop_context, all_excerpts, iteration)
            reflect_mode = str(self._last_reflect_mode)
            info_checks.append(asdict(info_check))
            retrieval_trace[-1]["reflect_mode"] = reflect_mode
            retrieval_trace[-1]["request_status"] = str(info_check.request_status)
            retrieval_trace[-1]["missing"] = list(getattr(info_check, "missing", []) or [])
            iteration_modes.append(
                {
                    "iteration": int(iteration),
                    "plan_mode": plan_mode,
                    "reflect_mode": reflect_mode,
                    "request_status": str(info_check.request_status),
                }
            )
            if (
                info_check.request_status == "need_more"
                and str(info_check.next_request).strip()
            ):
                follow_up_requests.append(str(info_check.next_request).strip())
            
            if info_check.request_status == "complete":
                engine_snapshot = self._research_engine_snapshot(iteration_modes)
                return ResearchResult(
                    plan=self._unique_preserve_order(all_plan),
                    memory_excerpts=all_excerpts[:self.MAX_EXCERPTS],
                    reflection=info_check.analysis,
                    should_continue=False,
                    iteration=iteration,
                    info_checks=info_checks,
                    retrieval_trace=retrieval_trace,
                    research_engine=engine_snapshot,
                )
        
        fallback_reflection = (
            info_checks[-1].get("analysis")
            if info_checks
            else f"Completed maximum {self._max_reflections} iterations."
        )
        engine_snapshot = self._research_engine_snapshot(iteration_modes)
        return ResearchResult(
            plan=self._unique_preserve_order(all_plan),
            memory_excerpts=all_excerpts[:self.MAX_EXCERPTS],
            reflection=str(fallback_reflection),
            should_continue=False,
            iteration=self._max_reflections,
            info_checks=info_checks,
            retrieval_trace=retrieval_trace,
            research_engine=engine_snapshot,
        )

    def _unique_preserve_order(self, items: List[str]) -> List[str]:
        seen: set[str] = set()
        output: List[str] = []
        for item in items:
            key = str(item).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(str(item).strip())
        return output

    def _research_engine_snapshot(self, iteration_modes: List[Dict[str, Any]]) -> Dict[str, Any]:
        plan_modes = [str(item.get("plan_mode", "")) for item in iteration_modes if str(item.get("plan_mode", "")).strip()]
        reflect_modes = [
            str(item.get("reflect_mode", ""))
            for item in iteration_modes
            if str(item.get("reflect_mode", "")).strip()
        ]
        return {
            "llm_enabled": bool(self._llm_enabled),
            "llm_mode": str(self._llm_mode),
            "llm_model": str(self._llm_model) if self._llm_enabled else "",
            "max_reflections": int(self._max_reflections),
            "llm_stats": dict(self._llm_stats),
            "plan_modes": plan_modes,
            "reflect_modes": reflect_modes,
            "iterations": [dict(item) for item in iteration_modes],
        }


class GAMMemorySystem:
    """
    Complete GAM-style memory system combining PageStore, Memorizer, and Researcher.
    """
    
    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        use_vector_search: bool = True,
        storage_path: Optional[str] = None,
        autosave: bool = True,
    ):
        """
        Initialize GAM memory system.
        
        Args:
            embedding_model: Sentence transformer model name
            use_vector_search: Whether to use vector search
        """
        self.page_store = PageStore(
            embedding_model=embedding_model,
            use_vector_search=use_vector_search
        )
        self.memorizer = Memorizer(self.page_store)
        self.researcher = Researcher(self.page_store)
        self.storage_path = (
            Path(storage_path).expanduser().resolve() if storage_path else None
        )
        self.autosave = bool(autosave)
        self._load_storage_if_available()
    
    def research(self, context: Dict[str, Any]) -> ResearchResult:
        """Execute research loop."""
        return self.researcher.research(context)
    
    # Legacy API (backward compatibility)
    def create_memo(self, **kwargs) -> Page:
        """Create a run memo (legacy method)."""
        return self.memorizer.create_memo(**kwargs)
    
    def add_page(self, **kwargs) -> Page:
        """Add a page to the store."""
        page = self.page_store.add_page(**kwargs)
        self._autosave()
        return page
    
    def search(self, query: str, top_k: int = 5, tenant_id: Optional[str] = None) -> List[Tuple[Page, float]]:
        """Hybrid search with optional tenant scoping."""
        return self.page_store.hybrid_search(query, top_k, tenant_id=tenant_id)
    
    # Enhanced session-based API
    def start_session(self, tenant_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Start a new GAM session."""
        return self.memorizer.start_session(tenant_id=tenant_id, metadata=metadata)
    
    def add_to_session(
        self, 
        session_id: str, 
        role: str, 
        content: str,
        tool_outputs: Optional[List[Dict[str, Any]]] = None,
        artifacts: Optional[List[Dict[str, Any]]] = None
    ):
        """Add content to active session."""
        return self.memorizer.add_to_session(
            session_id, role, content, tool_outputs, artifacts
        )
    
    def end_session_with_memo(
        self,
        session_id: str,
        spec_title: str,
        endpoints_count: int,
        tests_generated: int,
        key_decisions: List[str],
        issues_found: List[str]
    ) -> Tuple[List[Page], Page]:
        """End session and create lossless pages + contextual memo."""
        result = self.memorizer.end_session_with_memo(
            session_id, spec_title, endpoints_count, tests_generated,
            key_decisions, issues_found
        )
        self._autosave()
        return result

    def save(self) -> None:
        """Persist page store to disk if storage path is configured."""
        if self.storage_path is None:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": time.time(),
            "pages": self.page_store.export_pages(),
        }
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _autosave(self) -> None:
        if self.autosave:
            self.save()

    def _load_storage_if_available(self) -> None:
        if self.storage_path is None or not self.storage_path.exists():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            pages = raw.get("pages", [])
            if isinstance(pages, list) and pages:
                self.page_store.import_pages(pages, replace=True)
        except Exception:
            # Fall back to in-memory defaults if persistence file is invalid.
            return
