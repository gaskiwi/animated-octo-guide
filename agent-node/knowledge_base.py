"""
knowledge_base.py — Persistent semantic knowledge base for openclaw.

Uses ChromaDB (already installed) for vector storage and semantic search.
Also writes human-readable markdown notes for browsability.

Collections:
  research_findings  — indexed findings from pipeline research stages
  task_history       — complete stage outputs per run
  automation_scripts — successful /misc scripts for reuse

Storage layout on kamrui:
  /home/pacers4ever/knowledge_base/
    chroma/          — ChromaDB persistent storage
    notes/           — markdown exports (human-readable)
      YYYY-MM-DD/
        <run_id>_<task_slug>.md

Usage:
  from knowledge_base import KnowledgeBase
  kb = KnowledgeBase()

  # Store a pipeline stage output
  kb.store_stage(run_id, task, stage, content, score=8)

  # Query before research — get relevant prior knowledge
  prior = kb.query_prior_knowledge(topic, n=5)

  # Store a misc automation script
  kb.store_script(task, code, result)

  # Browse recent work
  recent = kb.recent_tasks(limit=10)
"""

import os
import re
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

KB_ROOT    = Path("/home/pacers4ever/knowledge_base")
CHROMA_DIR = KB_ROOT / "chroma"
NOTES_DIR  = KB_ROOT / "notes"


class KnowledgeBase:
    def __init__(self):
        KB_ROOT.mkdir(parents=True, exist_ok=True)
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        NOTES_DIR.mkdir(parents=True, exist_ok=True)

        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            self._research  = self._client.get_or_create_collection(
                "research_findings",
                metadata={"description": "Indexed research from pipeline runs"},
            )
            self._tasks     = self._client.get_or_create_collection(
                "task_history",
                metadata={"description": "Complete stage outputs per pipeline run"},
            )
            self._scripts   = self._client.get_or_create_collection(
                "automation_scripts",
                metadata={"description": "Successful /misc automation scripts"},
            )
            self._available = True
            log.info("KnowledgeBase ready — %d research docs, %d tasks, %d scripts",
                     self._research.count(), self._tasks.count(), self._scripts.count())
        except Exception as e:
            log.error("KnowledgeBase init failed: %s", e)
            self._available = False

    # ── Store pipeline stage output ────────────────────────────────────────────
    def store_stage(self, run_id: str, task: str, stage: str,
                    content: str, score: int = 0, model: str = "qwen"):
        """Store one pipeline stage output."""
        if not self._available:
            return
        try:
            doc_id   = f"{run_id}_{stage}"
            metadata = {
                "run_id":    run_id,
                "task":      task[:200],
                "stage":     stage,
                "score":     score,
                "model":     model,
                "date":      datetime.now().isoformat(),
                "task_slug": _slugify(task),
            }
            # Upsert (overwrite if retry improved the score)
            self._tasks.upsert(
                ids=[doc_id],
                documents=[content[:8000]],
                metadatas=[metadata],
            )
            log.info("KB stored: %s/%s (score=%d)", run_id, stage, score)

            # For research stage also index into research_findings for future queries
            if stage == "research":
                self._index_research(run_id, task, content)

        except Exception as e:
            log.error("KB store_stage failed: %s", e)

    # ── Store complete pipeline run and write markdown note ────────────────────
    def store_run(self, run_id: str, task: str, results: dict,
                  scores: dict, model: str = "qwen"):
        """
        Store a completed pipeline run and write a human-readable markdown note.
        results: {stage: output_text}
        scores:  {stage: score}
        """
        if not self._available:
            return
        try:
            # Build combined document for semantic search
            combined = f"TASK: {task}\n\n"
            combined += "\n\n".join(
                f"## {s.upper()} (score {scores.get(s, '?')}/10)\n{results.get(s, '')[:2000]}"
                for s in results
            )

            self._tasks.upsert(
                ids=[f"{run_id}_complete"],
                documents=[combined[:8000]],
                metadatas=[{
                    "run_id":     run_id,
                    "task":       task[:200],
                    "stage":      "complete",
                    "model":      model,
                    "date":       datetime.now().isoformat(),
                    "avg_score":  sum(scores.values()) / len(scores) if scores else 0,
                    "task_slug":  _slugify(task),
                    "stages":     ",".join(results.keys()),
                }],
            )

            # Write markdown note
            self._write_note(run_id, task, results, scores, model)
            log.info("KB run stored and note written: %s", run_id)

        except Exception as e:
            log.error("KB store_run failed: %s", e)

    # ── Store misc automation script ───────────────────────────────────────────
    def store_script(self, task: str, code: str, result: str = "",
                     success: bool = True):
        """Store a /misc generated script for future reuse."""
        if not self._available or not success:
            return
        try:
            doc_id = f"script_{hashlib.md5(task.encode()).hexdigest()[:12]}"
            self._scripts.upsert(
                ids=[doc_id],
                documents=[f"TASK: {task}\n\nCODE:\n{code}\n\nRESULT:\n{result[:500]}"],
                metadatas=[{
                    "task":    task[:200],
                    "date":    datetime.now().isoformat(),
                    "success": str(success),
                    "lines":   str(len(code.splitlines())),
                }],
            )
            log.info("KB script stored: %s", task[:60])
        except Exception as e:
            log.error("KB store_script failed: %s", e)

    # ── Query prior knowledge ──────────────────────────────────────────────────
    def query_prior_knowledge(self, topic: str, n: int = 4) -> str:
        """
        Semantic search across all past research and task history.
        Returns a formatted string ready to inject into a prompt as "Prior Knowledge".
        """
        if not self._available:
            return ""
        try:
            sections = []

            # Search research findings
            r_results = self._research.query(
                query_texts=[topic],
                n_results=min(n, max(1, self._research.count())),
            )
            r_docs  = r_results.get("documents", [[]])[0]
            r_metas = r_results.get("metadatas", [[]])[0]
            r_dists = r_results.get("distances", [[]])[0]

            relevant_research = [
                (doc, meta, dist)
                for doc, meta, dist in zip(r_docs, r_metas, r_dists)
                if dist < 1.2  # similarity threshold
            ]
            if relevant_research:
                sections.append("### Prior Research Findings")
                for doc, meta, dist in relevant_research[:3]:
                    sections.append(
                        f"**From run {meta.get('run_id', '?')} "
                        f"({meta.get('date', '')[:10]}) — "
                        f"Task: {meta.get('task', '')[:80]}**\n"
                        f"{doc[:800]}…\n"
                    )

            # Search task history
            if self._tasks.count() > 0:
                t_results = self._tasks.query(
                    query_texts=[topic],
                    n_results=min(3, self._tasks.count()),
                    where={"stage": "complete"},
                )
                t_docs  = t_results.get("documents", [[]])[0]
                t_metas = t_results.get("metadatas", [[]])[0]
                t_dists = t_results.get("distances", [[]])[0]

                relevant_tasks = [
                    (doc, meta, dist)
                    for doc, meta, dist in zip(t_docs, t_metas, t_dists)
                    if dist < 1.0
                ]
                if relevant_tasks:
                    sections.append("### Related Past Tasks")
                    for doc, meta, dist in relevant_tasks[:2]:
                        sections.append(
                            f"**{meta.get('task', '')[:80]}** "
                            f"(avg score {meta.get('avg_score', '?'):.1f}/10, "
                            f"{meta.get('date', '')[:10]})\n"
                            f"{doc[:600]}…\n"
                        )

            if not sections:
                return ""

            header = (
                "## Prior Knowledge (from knowledge base)\n"
                "_Retrieved from past pipeline runs — use these as additional context "
                "but verify with current sources._\n\n"
            )
            return header + "\n".join(sections)

        except Exception as e:
            log.error("KB query_prior_knowledge failed: %s", e)
            return ""

    def query_similar_scripts(self, task: str, n: int = 3) -> str:
        """Find past automation scripts relevant to this task."""
        if not self._available or self._scripts.count() == 0:
            return ""
        try:
            results = self._scripts.query(
                query_texts=[task],
                n_results=min(n, self._scripts.count()),
            )
            docs   = results.get("documents", [[]])[0]
            metas  = results.get("metadatas", [[]])[0]
            dists  = results.get("distances", [[]])[0]

            relevant = [(d, m) for d, m, dist in zip(docs, metas, dists) if dist < 0.9]
            if not relevant:
                return ""

            lines = ["## Similar Past Scripts\n"]
            for doc, meta in relevant[:2]:
                lines.append(f"**Past task:** {meta.get('task', '')[:80]}\n{doc[:600]}\n")
            return "\n".join(lines)
        except Exception as e:
            log.error("KB query_similar_scripts failed: %s", e)
            return ""

    def recent_tasks(self, limit: int = 10) -> list:
        """Return metadata for the most recent completed tasks."""
        if not self._available:
            return []
        try:
            results = self._tasks.get(where={"stage": "complete"})
            metas   = results.get("metadatas", [])
            metas.sort(key=lambda m: m.get("date", ""), reverse=True)
            return metas[:limit]
        except Exception as e:
            log.error("KB recent_tasks failed: %s", e)
            return []

    def stats(self) -> dict:
        """Return KB statistics."""
        if not self._available:
            return {"available": False}
        return {
            "available":        True,
            "research_docs":    self._research.count(),
            "task_stages":      self._tasks.count(),
            "scripts":          self._scripts.count(),
            "notes_dir":        str(NOTES_DIR),
            "chroma_dir":       str(CHROMA_DIR),
        }

    # ── Internal helpers ───────────────────────────────────────────────────────
    def _index_research(self, run_id: str, task: str, content: str):
        """Split research output into chunks and index each one."""
        # Split on section headers (## ) for meaningful chunks
        chunks = re.split(r"\n(?=##\s)", content)
        for i, chunk in enumerate(chunks[:10]):
            if len(chunk.strip()) < 100:
                continue
            doc_id = f"{run_id}_research_{i}"
            self._research.upsert(
                ids=[doc_id],
                documents=[chunk[:3000]],
                metadatas=[{
                    "run_id":    run_id,
                    "task":      task[:200],
                    "chunk":     i,
                    "date":      datetime.now().isoformat(),
                    "task_slug": _slugify(task),
                }],
            )

    def _write_note(self, run_id: str, task: str, results: dict,
                    scores: dict, model: str):
        """Write a human-readable markdown note for this run."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        day_dir  = NOTES_DIR / date_str
        day_dir.mkdir(exist_ok=True)

        filename = f"{run_id}_{_slugify(task)[:40]}.md"
        path     = day_dir / filename

        avg = sum(scores.values()) / len(scores) if scores else 0
        lines = [
            f"# {task}",
            f"",
            f"**Run ID:** `{run_id}`  ",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
            f"**Model:** {model}  ",
            f"**Avg Score:** {avg:.1f}/10  ",
            f"",
            "---",
            "",
        ]
        for stage, output in results.items():
            score = scores.get(stage, "?")
            lines += [
                f"## {stage.capitalize()} _(score: {score}/10)_",
                "",
                output,
                "",
                "---",
                "",
            ]

        path.write_text("\n".join(lines), encoding="utf-8")
        log.info("Note written: %s", path)


# ── Singleton ──────────────────────────────────────────────────────────────────
_kb_instance: Optional[KnowledgeBase] = None

def get_kb() -> KnowledgeBase:
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = KnowledgeBase()
    return _kb_instance


# ── Helpers ────────────────────────────────────────────────────────────────────
def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60]
