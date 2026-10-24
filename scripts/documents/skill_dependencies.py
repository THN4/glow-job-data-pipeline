"""Propose dependencies from prepared documents, review with a/r, and export/apply."""

import argparse
import json
from pathlib import Path

from src.documents.extraction.skill_dependencies import (
    apply_reviewed, lookup_verified, prepare_evidence, proposal_scope_flags, propose, read_manifest, save_manifest,
)
from src.documents.schemas.skill_dependency import Review


def connect():
    from src.shared.db.database import get_database_connection
    return get_database_connection()


def scope_flags(item):
    kind = item.review.dependency_type if item.review else item.proposal.dependency_type
    return sorted(set(item.scope_flags + proposal_scope_flags(
        item.proposal, item.source_title, dependency_type=kind,
    )))


def counts(manifest):
    return {"origin": manifest.origin, "target_skills": len(manifest.target_skills),
            "sources": manifest.source_count, "chunks_read": manifest.inspected_chunk_count,
            "chunks_remaining": manifest.omitted_chunk_count,
            "proposal_validation_failures": manifest.invalid_proposals,
            "total": len(manifest.items),
            "pending": sum(item.review is None for item in manifest.items),
            "pending_general": sum(item.review is None and item.proposal.scope == "general" and not scope_flags(item) for item in manifest.items),
            "pending_scoped": sum(item.review is None and item.proposal.scope in {"document_specific", "conditional"} for item in manifest.items),
            "pending_scope_questions": sum(item.review is None and (
                item.proposal.scope in {"unknown", "uncertain"}
                or (item.proposal.scope == "general" and bool(scope_flags(item)))
            ) for item in manifest.items),
            "approved": sum(bool(item.review and item.review.decision == "approve") for item in manifest.items),
            "rejected": sum(bool(item.review and item.review.decision == "reject") for item in manifest.items),
            "note": "Local approval is not DB application. Verified scoped rows are context only, not global ordering. Coverage remains unknown."}


def markdown(manifest):
    lines = ["# Skill dependency review", "",
             "Proposals only. Approval is a local decision; DB writes require a separate apply command.",
             "No edge / no proposal means unknown coverage, not no prerequisites.", "",
             "Only the prepared document corpus supplies relationship content. Catalog entries supply canonical IDs only.", "",
             f"Inspected chunks: {manifest.inspected_chunk_count}; omitted chunks: {manifest.omitted_chunk_count}.",
             f"Proposal validation failures recorded: {manifest.invalid_proposals} (attempts, not review rows).",
             "", "Target skills: " + ", ".join(skill["skill_name"] for skill in manifest.target_skills), ""]
    if manifest.target_evidence:
        lines.extend(["## Evidence inspected per target", "",
                      "Counts describe inspected material, not complete dependency coverage.", "",
                      "| Target | Inspected / mapped chunks | Inspected sources |",
                      "|---|---:|---:|"])
        for coverage in manifest.target_evidence:
            lines.append(f"| {coverage.skill_name} | {coverage.inspected_chunks} / {coverage.mapped_chunks} | {coverage.inspected_sources} |")
        lines.append("")
    for index, item in enumerate(manifest.items, 1):
        p, r = item.proposal, item.review
        lines.extend([
            f"## Row {index}: {item.prerequisite_name} → {item.target_name}", "",
            f"Canonical IDs: {p.prerequisite_skill_id} → {p.target_skill_id}", "",
            f"Proposed: {p.dependency_type}; strength={p.strength}; confidence={p.confidence}; scope={p.scope}", "",
            "Proposed scope condition: " + (p.scope_note or "not recorded; scoped approval requires an explicit condition"), "",
            "Scope flags: " + (", ".join(scope_flags(item)) or "none detected (not proof of general validity)"), "",
            f"Review: {r.decision if r else 'pending'}", "",
            f"Source {p.source_id}, chunk {p.chunk_id}: {item.source_title}", "",
            item.source_url or "(no URL)", "", "Evidence:", "",
            "\n".join("> " + line for line in p.evidence_text.splitlines()), "",
            "Reason / limitations: " + p.reason, "",
            "Basis: " + (p.basis or "legacy explicit-evidence proposal") + " (inferred = learning advice inferred from this passage, not an explicit prerequisite claim)", "",
        ])
        if r:
            lines.extend([f"Decision by {r.reviewer}: {r.note}", "",
                          f"Reviewed fields: {r.dependency_type}; {r.strength}; scope={r.scope}", "",
                          "Reviewed scope condition: " + (r.scope_note or "(general / unresolved)"), "",
                          "Runtime use: " + ("general relationship" if r.scope == "general" else "context only; applicability is not automatically satisfied"), ""])
    return "\n".join(lines)


def checkpoint(path, manifest):
    # Save authoritative JSON first; Markdown can always be regenerated by status.
    save_manifest(path, manifest)
    path.with_suffix(".md").write_text(markdown(manifest), encoding="utf-8")


def required_input(prompt):
    value = input(prompt).strip()
    if len(value) < 3:
        raise ValueError("A review note needs at least three nonblank characters")
    return value


def review_interactively(args, manifest):
    selected = list(enumerate(manifest.items, 1))
    if args.row is not None:
        if not 1 <= args.row <= len(selected):
            raise ValueError("Row is outside this manifest")
        selected = [selected[args.row - 1]]
    for index, item in selected:
        if item.review is not None and args.row is None and not args.include_reviewed:
            continue
        p = item.proposal
        flags = scope_flags(item)
        print(f"\nRow {index}: {item.prerequisite_name} ({p.prerequisite_skill_id}) -> {item.target_name} ({p.target_skill_id})")
        print(f"Proposed {p.dependency_type} / {p.strength}; scope={p.scope}; confidence={p.confidence}")
        if p.scope in {"document_specific", "conditional"}:
            print("Scoped approval is supported: preserve the condition below. This will be context only, not global ordering.")
        elif p.scope in {"unknown", "uncertain"} or flags:
            print("Scope needs resolution. Do not broaden a source condition into a general ordering rule.")
        print("Proposed condition: " + (p.scope_note or "not recorded; enter the condition during review"))
        if flags:
            print("Scope flags: " + ", ".join(flags))
        print(f"Source {p.source_id}, chunk {p.chunk_id}: {item.source_title}\n{item.source_url}")
        print(f"Evidence: {p.evidence_text}\nReason: {p.reason}\nBasis: {p.basis or 'legacy evidence'}")
        if item.review:
            print(f"Prior decision: {item.review.decision}: {item.review.note}")
        print("a=approve, r=reject, Enter=skip, q=quit (no reason required)")
        choice = input("> ").strip().lower()
        if choice == "q":
            break
        if not choice:
            continue
        if choice not in {"a", "e", "r"}:
            print("Unknown choice; left pending/unchanged.")
            continue
        prior = item.review
        kind, strength, scope = ((prior.dependency_type, prior.strength, prior.scope) if prior
                                else (p.dependency_type, p.strength, p.scope))
        scope_note = prior.scope_note if prior else p.scope_note
        if choice == "e":
            kind = input(f"Type prerequisite/recommended_before/related [{kind}]: ").strip() or kind
            strength = input(f"Strength required/strong/recommended/weak [{strength}]: ").strip() or strength
            scope = input(f"Scope general/document_specific/conditional/unknown [{scope}]: ").strip() or scope
        flags = sorted(set(item.scope_flags + proposal_scope_flags(p, item.source_title, dependency_type=kind)))
        if choice != "r" and scope in {"unknown", "uncertain"}:
            print("Resolve the scope before approval; keep pending or reject.")
            continue
        if choice != "r" and scope == "general" and flags:
            print("Evidence has scope conditions. Approve with its actual document/learner scope, or use different general evidence.")
            continue
        if choice != "r" and scope in {"document_specific", "conditional"}:
            if choice == "a" and scope == "document_specific" and not scope_note:
                scope_note = f"Limited to the document/audience: {item.source_title}"[:500]
            elif choice == "e":
                scope_note = input(f"Document/audience/learner condition [{scope_note or ''}]: ").strip() or scope_note
            if not scope_note or len(scope_note.strip()) < 3:
                print("Proposal lacks a learner condition; leave pending or reject. Current corpus generation fills this before review.")
                continue
        note = (required_input("Review reason (explain any scope/type correction): ") if choice == "e"
                else "Approved as proposed; no reviewer reason supplied." if choice == "a"
                else "Rejected by reviewer; no reason supplied.")
        decision = Review(
            decision="reject" if choice == "r" else "approve", reviewer=args.reviewer,
            note=note, proposal_fingerprint=item.proposal_fingerprint,
            dependency_type=kind, strength=strength, scope=scope,
            scope_note=scope_note,
        )
        # Validate before replacing any earlier decision.
        updated = item.model_copy(update={"review": decision})
        type(item).model_validate_json(updated.model_dump_json())
        manifest.items[index - 1] = updated
        checkpoint(args.manifest, manifest)
        print("Saved local checkpoint. No DB changes.")
    print(json.dumps(counts(manifest), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    corpus = commands.add_parser("corpus", help="Read all prepared active document chunks; resumable proposals with citations, no DB writes")
    corpus.add_argument("--output", type=Path, required=True)
    corpus.add_argument("--batch-size", type=int, default=24)
    corpus.add_argument("--max-chars", type=int, default=40000)
    exported = commands.add_parser("export", help="Export human-approved relationships for the AI team, without DB writes")
    exported.add_argument("--manifest", type=Path, required=True)
    exported.add_argument("--output", type=Path, required=True)
    proposed = commands.add_parser("propose", help="Inspect evidence; --generate makes one bounded text-model request")
    proposed.add_argument("--target", action="append", required=True)
    proposed.add_argument("--output", type=Path, required=True)
    proposed.add_argument("--max-chunks", type=int, default=18)
    proposed.add_argument("--max-chars", type=int, default=60000)
    generation = proposed.add_mutually_exclusive_group()
    generation.add_argument("--generate", action="store_true")
    generation.add_argument("--response-file", type=Path, help="Validate saved model/manual JSON instead of calling Bedrock")
    review = commands.add_parser("review")
    review.add_argument("--manifest", type=Path, required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--include-reviewed", action="store_true")
    review.add_argument("--row", type=int)
    status = commands.add_parser("status")
    status.add_argument("--manifest", type=Path, required=True)
    status.add_argument("--report", type=Path)
    applied = commands.add_parser("apply", help="Default is read-only dry-run; --apply writes approved edges only")
    applied.add_argument("--manifest", type=Path, required=True)
    applied.add_argument("--apply", action="store_true")
    commands.add_parser("list", help="Read verified active-source dependencies; no edges means unknown coverage")
    args = parser.parse_args()
    try:
        if args.command == "corpus":
            from src.documents.extraction.dependency_corpus import generate_corpus
            with connect() as connection:
                manifest = generate_corpus(connection, args.output, batch_size=args.batch_size,
                                           max_chars=args.max_chars, checkpoint=checkpoint)
            print(json.dumps(counts(manifest), ensure_ascii=False, indent=2))
        elif args.command == "propose":
            if args.output.suffix.lower() != ".json":
                raise ValueError("Output must end in .json")
            if args.output.exists():
                raise ValueError("Manifest already exists; review/resume it, or use a new output name")
            with connect() as connection:
                pack = prepare_evidence(connection, args.target, max_chunks=args.max_chunks, max_chars=args.max_chars)
            evidence_path = args.output.with_suffix(".evidence.json")
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"targets": pack["targets"], "inspected_chunks": len(pack["chunks"]),
                              "target_evidence": pack["target_evidence"],
                              "omitted_chunks": pack["omitted_chunk_count"], "evidence_file": str(evidence_path)}, ensure_ascii=False))
            if not args.generate and not args.response_file:
                print("Evidence preview only. Add --generate to call Nova, or --response-file to validate a saved response.")
                return
            def generate(prompt):
                if args.response_file:
                    return args.response_file.read_text(encoding="utf-8")
                from src.shared.llm.bedrock_client import nova_generate
                response = nova_generate(prompt)
                args.output.with_suffix(".response.json").write_text(response, encoding="utf-8")
                return response
            manifest = propose(pack, generate=generate)
            if args.response_file:
                manifest.model = "recorded_json_response"
            checkpoint(args.output, manifest)
            print(json.dumps(counts(manifest), ensure_ascii=False, indent=2))
        elif args.command == "list":
            with connect() as connection:
                edges = lookup_verified(connection)
            print(json.dumps({"coverage": "unknown", "verified_edges": edges}, ensure_ascii=False, indent=2, default=str))
        else:
            header = json.loads(args.manifest.read_text(encoding="utf-8"))
            if header.get("schema_version") == "bootstrap-1":
                raise ValueError("Catalog-only generation is outside the clarified scope. Use prepared-documents-v1.json from the prepared corpus.")
            manifest = read_manifest(args.manifest)
            if args.command == "review":
                review_interactively(args, manifest)
            elif args.command == "status":
                print(json.dumps(counts(manifest), ensure_ascii=False, indent=2))
                if args.report:
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(markdown(manifest), encoding="utf-8")
            elif args.command == "export":
                from src.documents.extraction.dependency_corpus import export_document_manifest
                if args.output.resolve() == args.manifest.resolve():
                    raise ValueError("Export must not overwrite the review manifest")
                print(json.dumps(export_document_manifest(manifest, args.output), ensure_ascii=False, indent=2))
            else:
                with connect() as connection:
                    print(json.dumps(apply_reviewed(connection, manifest, apply=args.apply), indent=2))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        print("Stopped. Previously saved review checkpoints are retained.")
    except RuntimeError as error:
        status = getattr(error.__cause__, "code", None)
        parser.exit(1, f"{error}; upstream_status={status or 'unknown'}. Saved checkpoints retained.\n")
    except Exception as error:
        parser.exit(1, f"Dependency workflow failed ({type(error).__name__}); no uncommitted DB changes were retained.\n")


if __name__ == "__main__":
    main()
