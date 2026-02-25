#!/usr/bin/env python3
"""
General Agentic Memory (GAM) Implementation

Based on the paper: "General Agentic Memory Via Deep Research" (arXiv:2511.18423)

This implements the GAM framework with:
1. Memorizer: Lightweight memory highlighting key historical information
2. Researcher: Retrieves and integrates information from page-store
3. Page-store: Universal storage for complete historical information
4. JIT compilation principles for runtime optimization
"""

import json
import time
import hashlib
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
from collections import defaultdict, deque
import pickle

# For embeddings and similarity search
try:
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    print("⚠️  sentence-transformers not available. Install with: pip install sentence-transformers")

# For BM25 search
try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False
    print("⚠️  rank-bm25 not available. Install with: pip install rank-bm25")


@dataclass
class MemoryPage:
    """A single page in the universal page-store."""
    page_id: str
    content: str
    metadata: Dict[str, Any]
    timestamp: float
    embedding: Optional[List[float]] = None
    importance_score: float = 0.0
    access_count: int = 0
    last_accessed: float = 0.0


@dataclass
class MemoryEntry:
    """Lightweight memory entry in the Memorizer."""
    entry_id: str
    summary: str
    page_ids: List[str]  # References to pages in page-store
    relevance_score: float
    created_at: float
    updated_at: float


@dataclass
class ResearchQuery:
    """Query for the Researcher component."""
    query_text: str
    context: Dict[str, Any]
    max_results: int = 10
    search_strategy: str = "hybrid"  # "semantic", "bm25", "hybrid"


@dataclass
class ResearchResult:
    """Result from the Researcher component."""
    pages: List[MemoryPage]
    integrated_context: str
    confidence_score: float
    search_time: float


class UniversalPageStore:
    """Universal storage for complete historical information."""
    
    def __init__(self, storage_path: str = "gam_pagestore"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)
        
        self.pages: Dict[str, MemoryPage] = {}
        self.embeddings_model = None
        self.bm25_index = None
        self.page_contents = []
        self.page_ids = []
        
        # Initialize embedding model if available
        if EMBEDDINGS_AVAILABLE:
            try:
                self.embeddings_model = SentenceTransformer('all-MiniLM-L6-v2')
                print("✅ Embeddings model loaded for semantic search")
            except Exception as e:
                print(f"⚠️  Failed to load embeddings model: {e}")
                self.embeddings_model = None
        
        # Load existing pages
        self._load_pages()
    
    def add_page(self, content: str, metadata: Dict[str, Any] = None) -> str:
        """Add a new page to the store."""
        if metadata is None:
            metadata = {}
        
        # Generate unique page ID
        page_id = hashlib.md5(f"{content}_{time.time()}".encode()).hexdigest()[:16]
        
        # Create embedding if model available
        embedding = None
        if self.embeddings_model:
            try:
                embedding = self.embeddings_model.encode(content).tolist()
            except Exception as e:
                print(f"⚠️  Failed to create embedding: {e}")
        
        # Create page
        page = MemoryPage(
            page_id=page_id,
            content=content,
            metadata=metadata,
            timestamp=time.time(),
            embedding=embedding,
            importance_score=self._calculate_importance(content, metadata),
            access_count=0,
            last_accessed=time.time()
        )
        
        # Store page
        self.pages[page_id] = page
        self.page_contents.append(content)
        self.page_ids.append(page_id)
        
        # Update BM25 index
        self._update_bm25_index()
        
        # Persist to disk
        self._save_page(page)
        
        return page_id
    
    def get_page(self, page_id: str) -> Optional[MemoryPage]:
        """Retrieve a page by ID."""
        if page_id in self.pages:
            page = self.pages[page_id]
            page.access_count += 1
            page.last_accessed = time.time()
            return page
        return None
    
    def search_semantic(self, query: str, max_results: int = 10) -> List[Tuple[str, float]]:
        """Semantic search using embeddings."""
        if not self.embeddings_model:
            return []
        
        try:
            query_embedding = self.embeddings_model.encode(query)
            
            results = []
            for page_id, page in self.pages.items():
                if page.embedding:
                    # Calculate cosine similarity
                    similarity = np.dot(query_embedding, page.embedding) / (
                        np.linalg.norm(query_embedding) * np.linalg.norm(page.embedding)
                    )
                    results.append((page_id, float(similarity)))
            
            # Sort by similarity and return top results
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:max_results]
        
        except Exception as e:
            print(f"⚠️  Semantic search failed: {e}")
            return []
    
    def search_bm25(self, query: str, max_results: int = 10) -> List[Tuple[str, float]]:
        """BM25 search for keyword matching."""
        if not BM25_AVAILABLE or not self.bm25_index:
            return []
        
        try:
            query_tokens = query.lower().split()
            scores = self.bm25_index.get_scores(query_tokens)
            
            # Get top results
            top_indices = np.argsort(scores)[::-1][:max_results]
            results = []
            
            for idx in top_indices:
                if idx < len(self.page_ids) and scores[idx] > 0:
                    results.append((self.page_ids[idx], float(scores[idx])))
            
            return results
        
        except Exception as e:
            print(f"⚠️  BM25 search failed: {e}")
            return []
    
    def search_hybrid(self, query: str, max_results: int = 10) -> List[Tuple[str, float]]:
        """Hybrid search combining semantic and BM25."""
        semantic_results = self.search_semantic(query, max_results * 2)
        bm25_results = self.search_bm25(query, max_results * 2)
        
        # Combine and normalize scores
        combined_scores = defaultdict(float)
        
        # Add semantic scores (weight: 0.6)
        for page_id, score in semantic_results:
            combined_scores[page_id] += score * 0.6
        
        # Add BM25 scores (weight: 0.4, normalized)
        if bm25_results:
            max_bm25_score = max(score for _, score in bm25_results)
            for page_id, score in bm25_results:
                normalized_score = score / max_bm25_score if max_bm25_score > 0 else 0
                combined_scores[page_id] += normalized_score * 0.4
        
        # Sort and return top results
        results = [(page_id, score) for page_id, score in combined_scores.items()]
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:max_results]
    
    def _calculate_importance(self, content: str, metadata: Dict[str, Any]) -> float:
        """Calculate importance score for a page."""
        score = 0.0
        
        # Length factor (longer content might be more important)
        score += min(len(content) / 1000, 1.0) * 0.3
        
        # Metadata factors
        if metadata.get("priority") == "high":
            score += 0.5
        elif metadata.get("priority") == "medium":
            score += 0.3
        
        if metadata.get("type") == "critical":
            score += 0.4
        
        # Keyword importance
        important_keywords = ["error", "critical", "important", "key", "main", "primary"]
        content_lower = content.lower()
        keyword_count = sum(1 for keyword in important_keywords if keyword in content_lower)
        score += min(keyword_count * 0.1, 0.3)
        
        return min(score, 1.0)
    
    def _update_bm25_index(self):
        """Update the BM25 index with current pages."""
        if not BM25_AVAILABLE:
            return
        
        try:
            tokenized_contents = [content.lower().split() for content in self.page_contents]
            if tokenized_contents:
                self.bm25_index = BM25Okapi(tokenized_contents)
        except Exception as e:
            print(f"⚠️  Failed to update BM25 index: {e}")
    
    def _save_page(self, page: MemoryPage):
        """Save a page to disk."""
        try:
            page_file = self.storage_path / f"{page.page_id}.pkl"
            with open(page_file, 'wb') as f:
                pickle.dump(page, f)
        except Exception as e:
            print(f"⚠️  Failed to save page {page.page_id}: {e}")
    
    def _load_pages(self):
        """Load existing pages from disk."""
        try:
            for page_file in self.storage_path.glob("*.pkl"):
                try:
                    with open(page_file, 'rb') as f:
                        page = pickle.load(f)
                        self.pages[page.page_id] = page
                        self.page_contents.append(page.content)
                        self.page_ids.append(page.page_id)
                except Exception as e:
                    print(f"⚠️  Failed to load page {page_file}: {e}")
            
            if self.pages:
                print(f"✅ Loaded {len(self.pages)} pages from storage")
                self._update_bm25_index()
        
        except Exception as e:
            print(f"⚠️  Failed to load pages: {e}")


class Memorizer:
    """Lightweight memory component that highlights key historical information."""
    
    def __init__(self, max_entries: int = 100):
        self.max_entries = max_entries
        self.entries: Dict[str, MemoryEntry] = {}
        self.entry_queue = deque()  # For LRU eviction
    
    def add_entry(self, summary: str, page_ids: List[str], relevance_score: float = 0.5) -> str:
        """Add a new memory entry."""
        entry_id = hashlib.md5(f"{summary}_{time.time()}".encode()).hexdigest()[:12]
        
        entry = MemoryEntry(
            entry_id=entry_id,
            summary=summary,
            page_ids=page_ids,
            relevance_score=relevance_score,
            created_at=time.time(),
            updated_at=time.time()
        )
        
        # Add entry
        self.entries[entry_id] = entry
        self.entry_queue.append(entry_id)
        
        # Evict old entries if necessary
        self._evict_if_needed()
        
        return entry_id
    
    def get_relevant_entries(self, query: str, max_entries: int = 10) -> List[MemoryEntry]:
        """Get relevant memory entries for a query."""
        query_lower = query.lower()
        
        # Simple relevance scoring based on keyword overlap
        scored_entries = []
        for entry in self.entries.values():
            summary_lower = entry.summary.lower()
            
            # Calculate keyword overlap
            query_words = set(query_lower.split())
            summary_words = set(summary_lower.split())
            overlap = len(query_words.intersection(summary_words))
            
            if overlap > 0:
                relevance = (overlap / len(query_words)) * entry.relevance_score
                scored_entries.append((entry, relevance))
        
        # Sort by relevance and return top entries
        scored_entries.sort(key=lambda x: x[1], reverse=True)
        return [entry for entry, _ in scored_entries[:max_entries]]
    
    def update_entry(self, entry_id: str, new_summary: str = None, new_relevance: float = None):
        """Update an existing memory entry."""
        if entry_id in self.entries:
            entry = self.entries[entry_id]
            if new_summary:
                entry.summary = new_summary
            if new_relevance is not None:
                entry.relevance_score = new_relevance
            entry.updated_at = time.time()
    
    def _evict_if_needed(self):
        """Evict old entries if we exceed max_entries."""
        while len(self.entries) > self.max_entries:
            # Remove oldest entry (LRU)
            oldest_id = self.entry_queue.popleft()
            if oldest_id in self.entries:
                del self.entries[oldest_id]


class Researcher:
    """Researcher component that retrieves and integrates information from page-store."""
    
    def __init__(self, page_store: UniversalPageStore, memorizer: Memorizer):
        self.page_store = page_store
        self.memorizer = memorizer
    
    def research(self, query: ResearchQuery) -> ResearchResult:
        """Conduct research for a given query."""
        start_time = time.time()
        
        # Step 1: Get relevant memory entries from Memorizer
        relevant_entries = self.memorizer.get_relevant_entries(query.query_text, 5)
        
        # Step 2: Search page-store based on strategy
        if query.search_strategy == "semantic":
            search_results = self.page_store.search_semantic(query.query_text, query.max_results)
        elif query.search_strategy == "bm25":
            search_results = self.page_store.search_bm25(query.query_text, query.max_results)
        else:  # hybrid
            search_results = self.page_store.search_hybrid(query.query_text, query.max_results)
        
        # Step 3: Retrieve pages and combine with memory entries
        pages = []
        page_ids_from_memory = set()
        
        # Add pages from memory entries
        for entry in relevant_entries:
            for page_id in entry.page_ids:
                page = self.page_store.get_page(page_id)
                if page:
                    pages.append(page)
                    page_ids_from_memory.add(page_id)
        
        # Add pages from search results
        for page_id, score in search_results:
            if page_id not in page_ids_from_memory:
                page = self.page_store.get_page(page_id)
                if page:
                    pages.append(page)
        
        # Step 4: Integrate information
        integrated_context = self._integrate_information(query, pages, relevant_entries)
        
        # Step 5: Calculate confidence score
        confidence_score = self._calculate_confidence(query, pages, search_results)
        
        search_time = time.time() - start_time
        
        return ResearchResult(
            pages=pages[:query.max_results],
            integrated_context=integrated_context,
            confidence_score=confidence_score,
            search_time=search_time
        )
    
    def _integrate_information(self, query: ResearchQuery, pages: List[MemoryPage], 
                             memory_entries: List[MemoryEntry]) -> str:
        """Integrate information from pages and memory entries."""
        context_parts = []
        
        # Add context from query
        if query.context:
            context_parts.append(f"Query Context: {json.dumps(query.context, indent=2)}")
        
        # Add memory summaries
        if memory_entries:
            memory_summaries = [entry.summary for entry in memory_entries]
            context_parts.append(f"Relevant Memory:\n" + "\n".join(f"- {summary}" for summary in memory_summaries))
        
        # Add page contents (truncated)
        if pages:
            page_contents = []
            for page in pages[:5]:  # Limit to top 5 pages
                content = page.content[:500] + "..." if len(page.content) > 500 else page.content
                page_contents.append(f"Page {page.page_id}: {content}")
            
            context_parts.append(f"Retrieved Information:\n" + "\n\n".join(page_contents))
        
        return "\n\n".join(context_parts)
    
    def _calculate_confidence(self, query: ResearchQuery, pages: List[MemoryPage], 
                            search_results: List[Tuple[str, float]]) -> float:
        """Calculate confidence score for the research result."""
        if not pages:
            return 0.0
        
        # Base confidence from search scores
        if search_results:
            avg_search_score = sum(score for _, score in search_results[:5]) / min(5, len(search_results))
            base_confidence = min(avg_search_score, 1.0)
        else:
            base_confidence = 0.5
        
        # Boost confidence based on page importance and recency
        importance_boost = sum(page.importance_score for page in pages[:3]) / min(3, len(pages))
        recency_boost = min(sum(1.0 / (time.time() - page.timestamp + 1) for page in pages[:3]) / 3, 0.3)
        
        confidence = min(base_confidence + importance_boost * 0.2 + recency_boost, 1.0)
        return confidence


class GeneralAgenticMemory:
    """Main GAM framework implementing JIT compilation principles for memory."""
    
    def __init__(self, storage_path: str = "gam_storage", max_memory_entries: int = 100):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)
        
        # Initialize components
        self.page_store = UniversalPageStore(str(self.storage_path / "pagestore"))
        self.memorizer = Memorizer(max_memory_entries)
        self.researcher = Researcher(self.page_store, self.memorizer)
        
        # Statistics
        self.stats = {
            "total_queries": 0,
            "total_pages_added": 0,
            "avg_research_time": 0.0,
            "cache_hits": 0
        }
        
        print("✅ General Agentic Memory (GAM) initialized")
    
    def add_information(self, content: str, metadata: Dict[str, Any] = None, 
                       create_memory_entry: bool = True) -> str:
        """Add new information to the system."""
        # Add to page store
        page_id = self.page_store.add_page(content, metadata or {})
        self.stats["total_pages_added"] += 1
        
        # Optionally create memory entry
        if create_memory_entry:
            summary = self._create_summary(content)
            self.memorizer.add_entry(summary, [page_id], self._calculate_relevance(content))
        
        return page_id
    
    def query(self, query_text: str, context: Dict[str, Any] = None, 
              max_results: int = 10, search_strategy: str = "hybrid") -> ResearchResult:
        """Query the GAM system for information."""
        self.stats["total_queries"] += 1
        
        # Create research query
        research_query = ResearchQuery(
            query_text=query_text,
            context=context or {},
            max_results=max_results,
            search_strategy=search_strategy
        )
        
        # Conduct research
        result = self.researcher.research(research_query)
        
        # Update statistics
        self.stats["avg_research_time"] = (
            (self.stats["avg_research_time"] * (self.stats["total_queries"] - 1) + result.search_time) 
            / self.stats["total_queries"]
        )
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        return {
            **self.stats,
            "total_pages": len(self.page_store.pages),
            "total_memory_entries": len(self.memorizer.entries),
            "storage_path": str(self.storage_path)
        }
    
    def _create_summary(self, content: str) -> str:
        """Create a summary of content for memory entry."""
        # Simple extractive summary (first sentence + key phrases)
        sentences = content.split('.')
        first_sentence = sentences[0].strip() if sentences else content[:100]
        
        # Add key phrases (simple heuristic)
        words = content.lower().split()
        important_words = [word for word in words if len(word) > 5 and word.isalpha()]
        key_phrases = ", ".join(important_words[:5])
        
        summary = f"{first_sentence}."
        if key_phrases:
            summary += f" Key terms: {key_phrases}"
        
        return summary[:200]  # Limit summary length
    
    def _calculate_relevance(self, content: str) -> float:
        """Calculate relevance score for content."""
        # Simple heuristic based on content characteristics
        score = 0.5  # Base score
        
        # Length factor
        if len(content) > 500:
            score += 0.2
        
        # Important keywords
        important_keywords = ["important", "critical", "key", "main", "primary", "essential"]
        content_lower = content.lower()
        keyword_count = sum(1 for keyword in important_keywords if keyword in content_lower)
        score += min(keyword_count * 0.1, 0.3)
        
        return min(score, 1.0)


# Example usage and testing
def demo_gam():
    """Demonstrate GAM functionality."""
    print("🚀 GAM (General Agentic Memory) Demo")
    print("=" * 50)
    
    # Initialize GAM
    gam = GeneralAgenticMemory()
    
    # Add some sample information
    print("\n📝 Adding sample information...")
    
    sample_data = [
        {
            "content": "Python is a high-level programming language known for its simplicity and readability. It supports multiple programming paradigms including procedural, object-oriented, and functional programming.",
            "metadata": {"type": "programming", "priority": "high", "topic": "python"}
        },
        {
            "content": "Machine learning is a subset of artificial intelligence that enables computers to learn and make decisions from data without being explicitly programmed for every task.",
            "metadata": {"type": "ai", "priority": "high", "topic": "machine_learning"}
        },
        {
            "content": "The GAM framework uses JIT compilation principles to create optimized contexts at runtime while maintaining lightweight memory during offline stages.",
            "metadata": {"type": "research", "priority": "critical", "topic": "gam"}
        },
        {
            "content": "Reinforcement learning is a type of machine learning where agents learn to make decisions by taking actions in an environment to maximize cumulative reward.",
            "metadata": {"type": "ai", "priority": "medium", "topic": "reinforcement_learning"}
        }
    ]
    
    for i, data in enumerate(sample_data):
        page_id = gam.add_information(data["content"], data["metadata"])
        print(f"  ✅ Added page {i+1}: {page_id}")
    
    # Test queries
    print("\n🔍 Testing queries...")
    
    test_queries = [
        "What is Python programming?",
        "How does machine learning work?",
        "Explain GAM framework",
        "What is reinforcement learning?"
    ]
    
    for query in test_queries:
        print(f"\n📋 Query: {query}")
        result = gam.query(query, max_results=3)
        
        print(f"  🎯 Confidence: {result.confidence_score:.3f}")
        print(f"  ⏱️  Search time: {result.search_time:.3f}s")
        print(f"  📄 Pages found: {len(result.pages)}")
        
        if result.pages:
            print(f"  📝 Top result: {result.pages[0].content[:100]}...")
    
    # Show statistics
    print(f"\n📊 System Statistics:")
    stats = gam.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n✅ GAM Demo completed!")


if __name__ == "__main__":
    demo_gam()
