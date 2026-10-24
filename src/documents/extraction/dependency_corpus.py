"""Read the prepared document corpus in full and checkpoint review proposals."""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.documents.schemas.skill_dependency import ReviewManifest, TargetEvidence
from src.documents.extraction.skill_dependencies import (
    rows, require_idle, propose, read_manifest, save_manifest, assert_acyclic,
)


def prepared_corpus(connection):
    require_idle(connection)
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        catalog = rows(connection, """
            SELECT skill_id, skill_name FROM core.skills
            WHERE catalog_status='approved' ORDER BY skill_id
        """)
        chunks = rows(connection, """
            SELECT c.chunk_id,c.source_id,c.topic,c.content,s.title,s.source_url,
                   array_agg(m.skill_id ORDER BY m.skill_id) AS mapped_skill_ids
            FROM knowledge.knowledge_chunks c
            JOIN knowledge.knowledge_sources s USING(source_id)
            JOIN knowledge.knowledge_chunk_skills m USING(chunk_id)
            JOIN core.skills sk ON sk.skill_id=m.skill_id
            WHERE s.is_active AND sk.catalog_status='approved'
            GROUP BY c.chunk_id,s.source_id ORDER BY c.source_id,c.chunk_id
        """)
    ids = {skill_id for chunk in chunks for skill_id in chunk["mapped_skill_ids"]}
    return {"origin": "document_evidence", "catalog": catalog,
            "targets": [skill for skill in catalog if skill["skill_id"] in ids],
            "chunks": chunks}


def edge_key(item):
    p = item.proposal
    key = (p.prerequisite_skill_id, p.target_skill_id, p.dependency_type, p.scope)
    if p.scope in {"document_specific", "conditional"}:
        key += (p.source_id, p.scope_note)
    return key


def evidence_counts(pack, processed):
    return [TargetEvidence(
        skill_id=target["skill_id"], skill_name=target["skill_name"],
        mapped_chunks=sum(target["skill_id"] in chunk["mapped_skill_ids"] for chunk in pack["chunks"]),
        inspected_chunks=sum(chunk["chunk_id"] in processed and target["skill_id"] in chunk["mapped_skill_ids"]
                             for chunk in pack["chunks"]),
        inspected_sources=len({chunk["source_id"] for chunk in pack["chunks"]
                               if chunk["chunk_id"] in processed and target["skill_id"] in chunk["mapped_skill_ids"]}),
    ) for target in pack["targets"]]


def validate_response(pack, raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {"proposals"} or not isinstance(data["proposals"], list):
        raise ValueError("Response must contain only a proposals list")
    if len(data["proposals"]) > 32:
        raise ValueError("Response exceeded the proposal budget")
    accepted, invalid = [], []
    for candidate in data["proposals"]:
        try:
            result = propose(pack, generate=lambda _: json.dumps({"proposals": [candidate]}, ensure_ascii=False),
                             allow_inference=True, max_proposals=32)
            accepted.extend(result.items)
        except ValueError as error:
            invalid.append({"proposal": candidate, "error": str(error)})
    return accepted, invalid


def generate_corpus(connection, output, *, batch_size=24, max_chars=40000, checkpoint=None):
    from src.shared.llm.bedrock_client import BedrockTextSettings, nova_generate

    output = Path(output)
    if output.suffix.lower() != ".json" or not 1 <= batch_size <= 40 or max_chars < 5000:
        raise ValueError("Use a JSON output, batch size 1..40 and at least 5000 characters per batch")
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_path = output.with_suffix(".evidence.json")
    if output.exists():
        manifest = read_manifest(output)
        if manifest.corpus_chunk_count is None or not evidence_path.exists():
            raise ValueError("Existing file is not a corpus run; choose another output filename")
        pack = json.loads(evidence_path.read_text(encoding="utf-8"))
        if manifest.target_skills != pack["targets"] or manifest.corpus_chunk_count != len(pack["chunks"]):
            raise ValueError("Corpus snapshot does not match this manifest")
    else:
        if evidence_path.exists():
            pack = json.loads(evidence_path.read_text(encoding="utf-8"))
        else:
            pack = prepared_corpus(connection)
            evidence_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        if not pack["chunks"]:
            raise ValueError("No prepared active document chunks with approved skill mappings")
        manifest = ReviewManifest(model=BedrockTextSettings().model_id, target_skills=pack["targets"],
                                  inspected_chunk_count=0, omitted_chunk_count=len(pack["chunks"]),
                                  corpus_chunk_count=len(pack["chunks"]),
                                  source_count=len({chunk["source_id"] for chunk in pack["chunks"]}), items=[])
        manifest.target_evidence = evidence_counts(pack, set())
        (checkpoint or save_manifest)(output, manifest)
    completed = set(manifest.processed_chunk_ids)
    if len(completed) != manifest.inspected_chunk_count or not completed <= {chunk["chunk_id"] for chunk in pack["chunks"]}:
        raise ValueError("Processed chunk checkpoint is inconsistent")
    remaining = [chunk for chunk in pack["chunks"] if chunk["chunk_id"] not in completed]
    batches, selected, char_count = [], [], 0
    for chunk in remaining:
        if len(chunk["content"]) > max_chars:
            raise ValueError(f"Chunk {chunk['chunk_id']} exceeds the character budget; increase --max-chars (no text is truncated)")
        if selected and (len(selected) >= batch_size or char_count + len(chunk["content"]) > max_chars):
            batches.append(selected)
            selected, char_count = [], 0
        selected.append(chunk)
        char_count += len(chunk["content"])
    if selected:
        batches.append(selected)
    for chunks in batches:
        batch_ids = {chunk["chunk_id"] for chunk in chunks}
        targets = {skill_id for chunk in chunks for skill_id in chunk["mapped_skill_ids"]}
        batch_pack = {"catalog": pack["catalog"],
                      "targets": [target for target in pack["targets"] if target["skill_id"] in targets],
                      "chunks": chunks, "omitted_chunk_count": 0}
        print(f"Reading prepared chunks {len(completed) + 1}..{len(completed) + len(chunks)}/{len(pack['chunks'])}", flush=True)
        correction, accepted, invalid, validation_failures = "", [], [], []
        response_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for attempt in range(3):
            def generate(prompt):
                # Keep the provider JSON mode; validate the richer nested contract
                # locally. The provider rejected this full proposal schema (400).
                raw = nova_generate(prompt + correction)
                raw_path = output.with_name(f"{output.stem}.chunks-{chunks[0]['chunk_id']}.{response_stamp}.attempt-{attempt + 1}.response.json")
                raw_path.write_text(raw, encoding="utf-8")
                return raw
            try:
                # Build the shared document prompt once, then validate each item
                # independently so one malformed quote cannot erase good proposals.
                captured = []
                def capture(prompt):
                    captured.append(prompt)
                    return '{"proposals": []}'
                propose(batch_pack, generate=capture, allow_inference=True, max_proposals=32)
                raw = generate(captured[0])
                valid, invalid = validate_response(batch_pack, raw)
                accepted.extend(valid)
                validation_failures.extend(invalid)
                if not invalid:
                    break
                correction = ("\nCorrect ONLY these rejected items, returning the same proposals JSON format. "
                              "Keep the exact original document quote. Omit a claim if the passage does not support it. "
                              "Do not repeat valid items already accepted. REJECTED ITEMS: "
                              + json.dumps(invalid, ensure_ascii=False))
            except ValueError as error:
                correction = f"\nThe previous response failed validation: {error}. Correct the response. Quotes must be copied exactly; return an empty list for unsupported relationships."
                if attempt == 2:
                    raise ValueError(f"Corpus batch failed; earlier checkpoints retained: {error}") from error
        if validation_failures:
            output.with_name(f"{output.stem}.chunks-{chunks[0]['chunk_id']}.{response_stamp}.invalid.json").write_text(
                json.dumps(validation_failures, ensure_ascii=False, indent=2), encoding="utf-8")
        # Reload so reviews saved while generation ran are not replaced.
        manifest = read_manifest(output)
        seen = {edge_key(item) for item in manifest.items}
        for item in accepted:
            key = edge_key(item)
            if key in seen:
                manifest.duplicate_proposals += 1
            else:
                manifest.items.append(item)
                seen.add(key)
        manifest.invalid_proposals += len(validation_failures)
        completed.update(batch_ids)
        manifest.processed_chunk_ids = sorted(completed)
        manifest.inspected_chunk_count = len(completed)
        manifest.omitted_chunk_count = len(pack["chunks"]) - len(completed)
        manifest.target_evidence = evidence_counts(pack, completed)
        (checkpoint or save_manifest)(output, manifest)
        print(json.dumps({"chunks_read": len(completed), "chunks_total": len(pack["chunks"]),
                          "relationships": len(manifest.items), "target_skills": len(manifest.target_skills)}, ensure_ascii=False), flush=True)
    return manifest


def export_document_manifest(manifest, output):
    edges = []
    for index, item in enumerate(manifest.items, 1):
        p, r = item.proposal, item.review
        if not r or r.decision != "approve":
            continue
        edges.append({"row": index, "prerequisite_skill_id": p.prerequisite_skill_id,
                      "target_skill_id": p.target_skill_id, "prerequisite_name": item.prerequisite_name,
                      "target_name": item.target_name, "dependency_type": r.dependency_type,
                      "strength": r.strength, "scope_type": r.scope, "scope_note": r.scope_note,
                      "explanation": p.reason, "basis": p.basis or "unclassified_legacy",
                      "source_id": p.source_id, "chunk_id": p.chunk_id,
                      "source_title": item.source_title, "source_url": item.source_url,
                      "evidence_text": p.evidence_text, "chunk_content_hash": item.chunk_content_hash,
                      "review": r.model_dump(), "origin": "document_evidence",
                      "runtime_role": "context_only" if r.scope != "general" else
                          "informational" if r.dependency_type == "related" else "global_ordering"})
    assert_acyclic(edges)
    payload = {"schema_version": "document-dependency-handoff-1", "origin": "document_evidence",
               "exported_at": datetime.now(timezone.utc).isoformat(),
               "review_summary": {"total": len(manifest.items), "approved": len(edges),
                                  "rejected": sum(bool(item.review and item.review.decision == "reject") for item in manifest.items),
                                  "pending": sum(item.review is None for item in manifest.items)},
               "target_skills": manifest.target_skills, "sources": manifest.source_count,
               "chunks_read": manifest.inspected_chunk_count, "chunks_remaining": manifest.omitted_chunk_count,
               "dependency_coverage": "unknown", "dependencies": edges,
               "contract": {"direction": "prerequisite_skill_id -> target_skill_id",
                            "inferred": "Learning advice inferred from the quoted document; not an explicit hard prerequisite",
                            "scoped_edges": "Context only; do not assume learner condition is satisfied",
                            "source_snapshot": "Evidence is from the local review snapshot; DB apply rechecks live content",
                            "pending_and_rejected": "Excluded"}}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"approved_exported": len(edges), "output": str(output), "db_writes": 0}
