# services/knowledge_service.py

import numpy as np
import faiss
import yaml
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from db.db_router import DatabaseRouter
from .text_embedding import embed_input
import logging

logger = logging.getLogger(__name__)

class KnowledgeService:
    """Knowledge service with runbook & incident memory RAG support."""

    def __init__(self, db_path: str = 'sqlite:///data/incident_copilot.db'):
        self.db_router = DatabaseRouter(db_path)
        self.db = self.db_router.knowledge
        self.index = None
        self.document_ids = []
        self.initialized = False

        # Runbook YAML directory
        self.runbook_dir = Path(__file__).parent.parent / 'data' / 'runbooks'

    async def initialize(self):
        """Initialize knowledge service with runbook + incident memory."""
        try:
            existing_docs = self.db.get_all_documents()

            if not existing_docs:
                logger.info("Database empty — loading runbooks from YAML")
                await self._load_runbooks_from_yaml()
            else:
                logger.info(f"Loaded {len(existing_docs)} documents from database")

            await self._build_vector_index()
            self.initialized = True
            logger.info("Knowledge service initialized (runbook mode)")

        except Exception as e:
            logger.error(f"Knowledge service initialization failed: {e}")
            raise

    async def _load_runbooks_from_yaml(self):
        """Load runbook YAML files into the knowledge database."""
        if not self.runbook_dir.exists():
            logger.warning(f"Runbook directory not found: {self.runbook_dir}")
            return

        yaml_files = list(self.runbook_dir.glob('*.yaml'))
        if not yaml_files:
            logger.warning(f"No YAML runbooks found in {self.runbook_dir}")
            return

        for yaml_path in yaml_files:
            try:
                with open(yaml_path, 'r', encoding='utf-8') as f:
                    runbook = yaml.safe_load(f)

                # Build searchable content from runbook structure
                content_parts = [
                    f"Incident ID: {runbook.get('incident_id', 'N/A')}",
                    f"Alert: {runbook.get('alert_name', 'N/A')}",
                    f"Service: {runbook.get('service', 'N/A')}",
                    f"Severity: {runbook.get('severity', 'N/A')}",
                    f"Symptoms: {runbook.get('symptoms', '')}",
                    f"Root Cause: {runbook.get('root_cause', '')}",
                    f"Resolution: {runbook.get('resolution', '')}",
                ]

                if runbook.get('runbook_steps'):
                    content_parts.append("Runbook Steps:")
                    content_parts.extend(runbook['runbook_steps'])

                if runbook.get('past_incidents'):
                    content_parts.append("Past Incidents:")
                    for past in runbook['past_incidents']:
                        content_parts.append(
                            f"  {past.get('id', 'N/A')} ({past.get('date', 'N/A')}): "
                            f"{past.get('root_cause', 'N/A')}"
                        )

                content = "\n".join(content_parts)

                # Keywords from tags + service + alert name
                keywords = runbook.get('tags', []) + [
                    runbook.get('service', ''),
                    runbook.get('alert_name', ''),
                ]
                keywords = [k for k in keywords if k]

                # Generate embedding
                text_for_embedding = f"{content} {' '.join(keywords)}"
                embedding = embed_input(text_for_embedding)

                # Save to database
                self.db.add_document(
                    content=content,
                    category=f"runbook:{runbook.get('service', 'unknown')}",
                    keywords=keywords,
                    embedding=embedding
                )
                logger.info(f"Loaded runbook: {yaml_path.name}")

            except Exception as e:
                logger.error(f"Failed to load {yaml_path.name}: {e}")

    async def _build_vector_index(self):
        """Build FAISS vector index from database embeddings."""
        try:
            documents = self.db.get_all_documents()
            if not documents:
                logger.warning("No documents available for index construction")
                return

            embeddings = []
            self.document_ids = []

            for doc in documents:
                if doc.get('embedding'):
                    embeddings.append(doc['embedding'])
                    self.document_ids.append(doc['id'])
                else:
                    logger.warning(f"Document {doc['id']} missing embedding — generating")
                    text_for_embedding = f"{doc['content']} {' '.join(doc.get('keywords', []))}"
                    embedding = embed_input(text_for_embedding)
                    self.db.update_document(doc['id'], embedding=embedding)
                    embeddings.append(embedding)
                    self.document_ids.append(doc['id'])

            if embeddings:
                embeddings_array = np.array(embeddings).astype('float32')
                dimension = embeddings_array.shape[1]
                self.index = faiss.IndexFlatIP(dimension)
                self.index.add(embeddings_array)
                logger.info(f"Vector index built with {len(embeddings)} embeddings")
            else:
                logger.warning("No valid embeddings — index not built")

        except Exception as e:
            logger.error(f"Vector index construction failed: {e}")
            raise

    async def search(self, query: str, top_k: int = 3, category: str = None) -> List[Dict]:
        """Search for relevant runbooks / incident memory."""
        if not self.initialized or self.index is None:
            logger.warning("Knowledge service not initialized or index unavailable")
            return []

        try:
            query_embedding = embed_input(query)
            query_array = np.array([query_embedding]).astype('float32')

            scores, indices = self.index.search(query_array, min(top_k * 2, len(self.document_ids)))

            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < len(self.document_ids):
                    doc_id = self.document_ids[idx]
                    doc = self.db.get_document(doc_id)

                    if doc:
                        if category and doc.get('category') != category:
                            continue

                        doc['score'] = float(score)
                        doc['rank'] = len(results) + 1
                        results.append(doc)

                        if len(results) >= top_k:
                            break

            return results

        except Exception as e:
            logger.error(f"Knowledge search failed: {e}")
            return []

    async def add_document(self, content: str, category: str, keywords: List[str] = None) -> bool:
        """Add a new document (runbook or incident postmortem)."""
        try:
            if keywords is None:
                keywords = []

            text_for_embedding = f"{content} {' '.join(keywords)}"
            embedding = embed_input(text_for_embedding)

            doc_id = self.db.add_document(content, category, keywords, embedding)
            await self._build_vector_index()

            logger.info(f"Document added {doc_id}: {content[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Document addition failed: {e}")
            return False

    async def update_document(self, doc_id: int, content: str = None, category: str = None, keywords: List[str] = None) -> bool:
        """Update an existing document."""
        try:
            embedding = None
            if content is not None or keywords is not None:
                current_doc = self.db.get_document(doc_id)
                if not current_doc:
                    return False

                final_content = content if content is not None else current_doc['content']
                final_keywords = keywords if keywords is not None else current_doc.get('keywords', [])

                text_for_embedding = f"{final_content} {' '.join(final_keywords)}"
                embedding = embed_input(text_for_embedding)

            success = self.db.update_document(doc_id, content, category, keywords, embedding)

            if success and embedding is not None:
                await self._build_vector_index()

            return success

        except Exception as e:
            logger.error(f"Document update failed: {e}")
            return False

    async def delete_document(self, doc_id: int, soft_delete: bool = True) -> bool:
        """Delete a document."""
        try:
            success = self.db.delete_document(doc_id, soft_delete)
            if success:
                await self._build_vector_index()
            return success
        except Exception as e:
            logger.error(f"Document deletion failed: {e}")
            return False

    def get_all_documents(self, include_inactive: bool = False) -> List[Dict]:
        return self.db.get_all_documents(include_inactive)

    def get_document(self, doc_id: int) -> Dict:
        return self.db.get_document(doc_id)

    def get_all_categories(self) -> List[str]:
        return self.db.get_all_categories()

    def get_documents_count(self) -> int:
        return self.db.get_documents_count()

    def search_by_category(self, category: str) -> List[Dict]:
        return self.db.search_documents_by_category(category)

    def search_by_keywords(self, keywords: List[str]) -> List[Dict]:
        return self.db.search_documents_by_keywords(keywords)
