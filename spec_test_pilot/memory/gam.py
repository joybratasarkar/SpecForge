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
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Literal
from datetime import datetime
import numpy as np

from rank_bm25 import BM25Okapi
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    VECTOR_SEARCH_AVAILABLE = False


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
class Page:
    """A page in the memory store."""
    id: str
    title: str
    tags: List[str]
    content: str
    timestamp: float = field(default_factory=time.time)
    source: Literal["convention", "existing_tests", "runbook", "validator", "memo"] = "memo"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "tags": self.tags,
            "content": self.content,
            "timestamp": self.timestamp,
            "source": self.source
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
        
        # Load default conventions
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
    
    def add_page(
        self,
        title: str,
        tags: List[str],
        content: str,
        source: Literal["convention", "existing_tests", "runbook", "validator", "memo"] = "memo"
    ) -> Page:
        """
        Add a new page to the store.
        
        Args:
            title: Page title
            tags: List of tags
            content: Page content
            source: Source type
            
        Returns:
            Created Page
        """
        page_id = self._generate_id(title, content)
        page = Page(
            id=page_id,
            title=title,
            tags=tags,
            content=content,
            source=source
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
    
    def get_page(self, page_id: str) -> Optional[Page]:
        """Get page by ID."""
        idx = self._id_to_idx.get(page_id)
        if idx is not None:
            return self.pages[idx]
        return None
    
    def search_bm25(self, query: str, top_k: int = 5) -> List[Tuple[Page, float]]:
        """
        Search pages using BM25.
        
        Args:
            query: Search query
            top_k: Number of results
            
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
            if scores[idx] > 0:
                results.append((self.pages[idx], float(scores[idx])))
        
        return results
    
    def search_vector(self, query: str, top_k: int = 5) -> List[Tuple[Page, float]]:
        """
        Search pages using vector similarity.
        
        Args:
            query: Search query
            top_k: Number of results
            
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
            if idx >= 0 and score > 0:
                results.append((self.pages[idx], float(score)))
        
        return results
    
    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        bm25_weight: float = 0.5
    ) -> List[Tuple[Page, float]]:
        """
        Hybrid search combining BM25 and vector search.
        
        Args:
            query: Search query
            top_k: Number of results
            bm25_weight: Weight for BM25 scores (1 - bm25_weight for vector)
            
        Returns:
            List of (Page, score) tuples
        """
        bm25_results = self.search_bm25(query, top_k * 2)
        vector_results = self.search_vector(query, top_k * 2)
        
        # Normalize and combine scores
        page_scores: Dict[str, float] = {}
        
        # Normalize BM25 scores
        if bm25_results:
            max_bm25 = max(s for _, s in bm25_results)
            for page, score in bm25_results:
                normalized = score / max_bm25 if max_bm25 > 0 else 0
                page_scores[page.id] = bm25_weight * normalized
        
        # Normalize and add vector scores
        if vector_results:
            max_vec = max(s for _, s in vector_results)
            for page, score in vector_results:
                normalized = score / max_vec if max_vec > 0 else 0
                page_scores[page.id] = page_scores.get(page.id, 0) + (1 - bm25_weight) * normalized
        
        # Sort by combined score
        sorted_ids = sorted(page_scores.keys(), key=lambda x: page_scores[x], reverse=True)
        
        results = []
        for page_id in sorted_ids[:top_k]:
            page = self.get_page(page_id)
            if page:
                results.append((page, page_scores[page_id]))
        
        return results
    
    def search_by_tags(self, tags: List[str], top_k: int = 5) -> List[Page]:
        """Search pages by tags."""
        tag_set = set(tags)
        scored = []
        for page in self.pages:
            overlap = len(tag_set & set(page.tags))
            if overlap > 0:
                scored.append((page, overlap))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in scored[:top_k]]


class Memorizer:
    """
    Produces memos from agent runs and stores artifacts as pages.
    """
    
    def __init__(self, page_store: PageStore):
        """
        Initialize Memorizer.
        
        Args:
            page_store: PageStore instance
        """
        self.page_store = page_store
    
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


class Researcher:
    """
    Deep-research loop: plan → search → integrate → reflect.
    
    Max 2 iterations per the spec requirement.
    """
    
    MAX_REFLECTIONS = 2
    MAX_EXCERPTS = 5
    MAX_EXCERPT_LENGTH = 200  # ~2 lines
    
    def __init__(self, page_store: PageStore):
        """
        Initialize Researcher.
        
        Args:
            page_store: PageStore instance
        """
        self.page_store = page_store
    
    def plan(self, context: Dict[str, Any]) -> List[str]:
        """
        Create research plan based on context.
        
        Args:
            context: Dict with spec_title, endpoints, auth_type, etc.
            
        Returns:
            List of plan steps
        """
        plan = []
        
        # Always look for conventions
        plan.append("Search for REST API testing conventions")
        
        # Auth-specific research
        auth_type = context.get("auth_type", "unknown")
        if auth_type not in ["none", "unknown"]:
            plan.append(f"Search for {auth_type} authentication testing patterns")
        
        # Endpoint-specific research
        endpoints = context.get("endpoints", [])
        methods = set(e.get("method", "") for e in endpoints)
        
        if "POST" in methods or "PUT" in methods:
            plan.append("Search for request validation testing patterns")
        
        if any("list" in e.get("path", "").lower() or 
               e.get("path", "").endswith("s") 
               for e in endpoints):
            plan.append("Search for pagination testing patterns")
        
        return plan[:4]  # Limit plan steps
    
    def search(self, plan: List[str]) -> List[Tuple[Page, float]]:
        """
        Execute search based on plan.
        
        Args:
            plan: List of search queries
            
        Returns:
            List of (Page, score) tuples
        """
        all_results: Dict[str, Tuple[Page, float]] = {}
        
        for query in plan:
            results = self.page_store.hybrid_search(query, top_k=3)
            for page, score in results:
                if page.id not in all_results or all_results[page.id][1] < score:
                    all_results[page.id] = (page, score)
        
        # Sort by score and return
        sorted_results = sorted(all_results.values(), key=lambda x: x[1], reverse=True)
        return sorted_results[:self.MAX_EXCERPTS * 2]
    
    def integrate(
        self,
        search_results: List[Tuple[Page, float]]
    ) -> List[Dict[str, str]]:
        """
        Integrate search results into memory excerpts.
        
        Args:
            search_results: List of (Page, score) tuples
            
        Returns:
            List of memory excerpt dicts
        """
        excerpts = []
        
        for page, score in search_results[:self.MAX_EXCERPTS]:
            # Truncate content to ~2 lines
            content = page.content
            if len(content) > self.MAX_EXCERPT_LENGTH:
                content = content[:self.MAX_EXCERPT_LENGTH] + "..."
            
            excerpts.append({
                "source": page.source,
                "excerpt": content
            })
        
        return excerpts
    
    def reflect(
        self,
        context: Dict[str, Any],
        excerpts: List[Dict[str, str]],
        iteration: int
    ) -> Tuple[str, bool]:
        """
        Reflect on research quality and decide if another iteration is needed.
        
        Args:
            context: Research context
            excerpts: Current excerpts
            iteration: Current iteration number
            
        Returns:
            (reflection_text, should_continue)
        """
        if iteration >= self.MAX_REFLECTIONS:
            return (
                f"Completed {iteration} research iterations. "
                f"Found {len(excerpts)} relevant excerpts covering conventions and patterns.",
                False
            )
        
        # Check coverage
        sources = set(e["source"] for e in excerpts)
        missing = []
        
        if "convention" not in sources:
            missing.append("testing conventions")
        
        auth_type = context.get("auth_type", "unknown")
        if auth_type not in ["none", "unknown"] and not any(
            "auth" in e["excerpt"].lower() for e in excerpts
        ):
            missing.append("auth testing patterns")
        
        if missing and iteration < self.MAX_REFLECTIONS:
            return (
                f"Iteration {iteration}: Found {len(excerpts)} excerpts. "
                f"Missing coverage for: {', '.join(missing)}. Continuing research.",
                True
            )
        
        return (
            f"Research complete after {iteration} iteration(s). "
            f"Found {len(excerpts)} relevant excerpts from {len(sources)} sources.",
            False
        )
    
    def research(self, context: Dict[str, Any]) -> ResearchResult:
        """
        Execute full research loop.
        
        Args:
            context: Dict with spec_title, endpoints, auth_type, etc.
            
        Returns:
            ResearchResult with plan, excerpts, and reflection
        """
        all_excerpts: List[Dict[str, str]] = []
        all_plan: List[str] = []
        
        for iteration in range(1, self.MAX_REFLECTIONS + 1):
            # Plan
            plan = self.plan(context)
            all_plan.extend(plan)
            
            # Search
            results = self.search(plan)
            
            # Integrate
            excerpts = self.integrate(results)
            
            # Deduplicate excerpts
            seen = set()
            for exc in excerpts:
                key = exc["excerpt"][:50]
                if key not in seen:
                    seen.add(key)
                    all_excerpts.append(exc)
            
            # Reflect
            reflection, should_continue = self.reflect(context, all_excerpts, iteration)
            
            if not should_continue:
                return ResearchResult(
                    plan=list(set(all_plan)),
                    memory_excerpts=all_excerpts[:self.MAX_EXCERPTS],
                    reflection=reflection,
                    should_continue=False,
                    iteration=iteration
                )
        
        return ResearchResult(
            plan=list(set(all_plan)),
            memory_excerpts=all_excerpts[:self.MAX_EXCERPTS],
            reflection=f"Completed maximum {self.MAX_REFLECTIONS} iterations.",
            should_continue=False,
            iteration=self.MAX_REFLECTIONS
        )


class GAMMemorySystem:
    """
    Complete GAM-style memory system combining PageStore, Memorizer, and Researcher.
    """
    
    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",
        use_vector_search: bool = True
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
    
    def research(self, context: Dict[str, Any]) -> ResearchResult:
        """Execute research loop."""
        return self.researcher.research(context)
    
    def create_memo(self, **kwargs) -> Page:
        """Create a run memo."""
        return self.memorizer.create_memo(**kwargs)
    
    def add_page(self, **kwargs) -> Page:
        """Add a page to the store."""
        return self.page_store.add_page(**kwargs)
    
    def search(self, query: str, top_k: int = 5) -> List[Tuple[Page, float]]:
        """Hybrid search."""
        return self.page_store.hybrid_search(query, top_k)
