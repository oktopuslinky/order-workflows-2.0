"""Build the in-memory graph from curated domain, journey, and shared specs.

Pipeline:
    <curated>/domains/*.domain.yaml  ->  typed nodes + edges  ->  Graph

Emits:
  * Hierarchy (CONTAINS): Domain -> Subdomain -> Stage, Service -> Endpoint -> Schema
  * Business flow:        Stage -PRECEDES-> Stage, Stage -TRIGGERS-> Service
  * Technical:            Service -REALIZES-> Stage, Endpoint -USES_SCHEMA-> Schema,
                          Service -DOCUMENTED_BY-> Document, Domain -OWNED_BY-> Team
  * Explicit `edges:` from each spec (including cross-domain DEPENDS_ON)

Cross-domain edge targets are resolved after ALL domains are loaded; unresolved
endpoints are reported (not silently dropped). `team.*` ids are auto-created.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import yaml

from ..paths import TELECOM_DOMAINS, TELECOM_JOURNEYS, TELECOM_SHARED
from ..model.schema import (
    Confidence,
    Edge,
    EdgeType,
    Graph,
    Node,
    NodeType,
    Source,
)

DOMAINS_DIR = TELECOM_DOMAINS
JOURNEYS_DIR = TELECOM_JOURNEYS
SHARED_DIR = TELECOM_SHARED


def est_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) used by budgeted assembly."""
    return max(1, round(len(text or "") / 4))


def _team_id(team_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", team_name.strip().lower()).strip("_")
    return f"team.{slug}"


def _artifact_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return f"artifact.{slug}"


def _humanize(slug: str) -> str:
    return slug.replace("_", " ").strip().capitalize()


def load_domain_specs(domains_dir: Path = DOMAINS_DIR) -> list[dict]:
    specs = []
    for path in sorted(domains_dir.glob("*.domain.yaml")):
        if path.name.startswith("_"):
            continue
        specs.append(yaml.safe_load(path.read_text()))
    return specs


def load_journey_specs(journeys_dir: Path = JOURNEYS_DIR) -> list[dict]:
    specs = []
    if not journeys_dir.exists():
        return specs
    for path in sorted(journeys_dir.glob("*.journey.yaml")):
        if path.name.startswith("_"):
            continue
        specs.append(yaml.safe_load(path.read_text()))
    return specs


def load_shared_specs(shared_dir: Path = SHARED_DIR) -> list[dict]:
    specs = []
    if not shared_dir.exists():
        return specs
    for path in sorted(shared_dir.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        specs.append(yaml.safe_load(path.read_text()))
    return specs


def _emit_shared(graph: Graph, spec: dict) -> None:
    """Register shared sub-nodes (schemas/documents/configs) used by MANY parents.

    These live in the synthetic `shared` domain and are referenced by id from
    services across domains, so the same sub-node is common to multiple nodes
    (a true many-to-many, not a duplicated copy per parent).
    """
    block = spec.get("shared", spec)  # allow top-level `shared:` or a bare doc
    for sc in block.get("schemas", []) or []:
        fields = ", ".join(sc.get("fields", []))
        _add_node(graph, sc["id"], NodeType.SCHEMA, sc["name"], domain="shared",
                  summary=f"{sc['name']} schema: {fields}",
                  metadata={"fields": sc.get("fields", []),
                            "required": sc.get("required", []), "shared": True})
    for doc in block.get("documents", []) or []:
        _add_node(graph, doc["id"], NodeType.DOCUMENT, doc.get("title", doc["id"]),
                  domain="shared", summary=doc.get("title", ""),
                  metadata={"path": doc.get("path"), "shared": True})
    for cfg in block.get("configs", []) or []:
        _add_node(graph, cfg["id"], NodeType.CONFIG, cfg.get("name", cfg["id"]),
                  domain="shared", summary=cfg.get("name", cfg["id"]),
                  metadata={"path": cfg.get("path"), "shared": True})


def _add_node(graph: Graph, nid: str, ntype: NodeType, name: str, *,
              domain: str | None = None, summary: str = "", **meta) -> Node:
    node = Node(
        id=nid, type=ntype, name=name, domain=domain,
        summary=summary, summary_tokens=est_tokens(summary),
        metadata=meta.pop("metadata", {}) or {},
        documentation=meta.pop("documentation", []) or [],
    )
    return graph.add_node(node)


def _emit_domain(graph: Graph, spec: dict) -> None:
    d = spec["domain"]
    did = d["id"]
    _add_node(graph, did, NodeType.DOMAIN, d["name"], domain=did,
              summary=d.get("summary", ""))

    # Team / ownership
    if d.get("team"):
        tid = _team_id(d["team"])
        _add_node(graph, tid, NodeType.TEAM, d["team"], summary=f"Team: {d['team']}")
        graph.add_edge(Edge(EdgeType.OWNED_BY, did, tid))

    # Layer 1 — subdomains and stages
    for sub in spec.get("subdomains", []):
        sid = sub["id"]
        _add_node(graph, sid, NodeType.SUBDOMAIN, sub["name"], domain=did,
                  summary=sub.get("summary", ""))
        graph.add_edge(Edge(EdgeType.CONTAINS, did, sid))
        for stage in sub.get("stages", []):
            stid = stage["id"]
            _add_node(graph, stid, NodeType.STAGE, stage["name"], domain=did,
                      summary=stage.get("summary", ""),
                      metadata=stage.get("metadata", {}))
            graph.add_edge(Edge(EdgeType.CONTAINS, sid, stid))
            if stage.get("precedes"):
                graph.add_edge(Edge(EdgeType.PRECEDES, stid, stage["precedes"]))
            # Data artifacts: model declared inputs/outputs as first-class nodes
            # so the latent data-flow becomes a queryable business workflow.
            for out_name in stage.get("outputs", []) or []:
                aid = _artifact_id(out_name)
                _add_node(graph, aid, NodeType.DATA_ARTIFACT, _humanize(str(out_name)),
                          summary=f"Business object: {out_name}")
                graph.add_edge(Edge(EdgeType.PRODUCES, stid, aid))
            for in_name in stage.get("inputs", []) or []:
                aid = _artifact_id(in_name)
                _add_node(graph, aid, NodeType.DATA_ARTIFACT, _humanize(str(in_name)),
                          summary=f"Business object: {in_name}")
                graph.add_edge(Edge(EdgeType.CONSUMES, stid, aid))

    # Layer 2 — services, endpoints, schemas, documents
    for svc in spec.get("services", []):
        svid = svc["id"]
        _add_node(graph, svid, NodeType.SERVICE, svc["name"], domain=did,
                  summary=svc.get("summary", ""), metadata=svc.get("metadata", {}))
        # A service may realize one (`realizes_stage`) or many (`realizes_stages`)
        # business stages. Each realization also auto-emits the Stage -> Service
        # TRIGGERS edge so the business->technical handoff is never missing.
        realized = list(svc.get("realizes_stages", []) or [])
        if svc.get("realizes_stage"):
            realized.append(svc["realizes_stage"])
        for stage_id in dict.fromkeys(realized):
            graph.add_edge(Edge(EdgeType.REALIZES, svid, stage_id))
            graph.add_edge(Edge(EdgeType.TRIGGERS, stage_id, svid))
        for i, doc in enumerate(svc.get("documentation", [])):
            # Prefer an explicit, stable id so the doc can be referenced in
            # `edges:` (e.g. a RELATES_TO between two documents). Fall back to a
            # positional id when none is declared.
            doc_id = doc.get("id") or f"doc.{svid}.{i}"
            _add_node(graph, doc_id, NodeType.DOCUMENT, doc.get("title", doc_id),
                      domain=did, summary=doc.get("title", ""),
                      metadata={"path": doc.get("path")})
            graph.add_edge(Edge(EdgeType.DOCUMENTED_BY, svid, doc_id))
        for ep in svc.get("endpoints", []):
            epid = ep["id"]
            ep_summary = f"{ep.get('method', 'GET')} {ep.get('path', '')}".strip()
            _add_node(graph, epid, NodeType.ENDPOINT, ep_summary, domain=did,
                      summary=ep_summary,
                      metadata={"method": ep.get("method"), "path": ep.get("path")})
            graph.add_edge(Edge(EdgeType.CONTAINS, svid, epid))
            graph.add_edge(Edge(EdgeType.IMPLEMENTS, svid, epid))
            if ep.get("schema_ref"):
                graph.add_edge(Edge(EdgeType.USES_SCHEMA, epid, ep["schema_ref"]))
        # Shared sub-node references: the same schema/document/config node is
        # reused by many services (many-to-many). Targets resolved after load.
        for sref in svc.get("uses_schemas", []) or []:
            graph.add_edge(Edge(EdgeType.USES_SCHEMA, svid, sref))
        for dref in svc.get("documents", []) or []:
            graph.add_edge(Edge(EdgeType.DOCUMENTED_BY, svid, dref))
        for cref in svc.get("reads_config", []) or []:
            graph.add_edge(Edge(EdgeType.READS_CONFIG, svid, cref))

    for sc in spec.get("schemas", []):
        scid = sc["id"]
        fields = ", ".join(sc.get("fields", []))
        _add_node(graph, scid, NodeType.SCHEMA, sc["name"], domain=did,
                  summary=f"{sc['name']} schema: {fields}",
                  metadata={"fields": sc.get("fields", []),
                            "required": sc.get("required", [])})


def _emit_explicit_edges(graph: Graph, spec: dict, dangling: list[str]) -> None:
    did = spec["domain"]["id"]
    existing = {(e.type, e.src, e.dst) for e in graph.edges}
    for e in spec.get("edges", []):
        etype = EdgeType(e["type"])
        src, dst = e["from"], e["to"]
        # auto-create referenced team nodes
        for ref in (src, dst):
            if ref.startswith("team.") and ref not in graph.nodes:
                _add_node(graph, ref, NodeType.TEAM, ref.split(".", 1)[1])
        if (etype, src, dst) in existing:
            continue  # already emitted (e.g. an auto TRIGGERS); don't duplicate
        existing.add((etype, src, dst))
        graph.add_edge(Edge(
            etype, src, dst,
            attributes=e.get("attributes", {}) or {},
            confidence=Confidence(e.get("confidence", "confirmed")),
            source=Source(e.get("source", "static")),
            weight=1.0 if e.get("confidence", "confirmed") == "confirmed" else 0.5,
        ))
        for ref in (src, dst):
            if ref not in graph.nodes:
                dangling.append(f"{did}: edge {etype.value} references missing '{ref}'")


def _derive_data_flow(graph: Graph) -> int:
    """Derive Stage -FLOWS_TO-> Stage from shared data artifacts.

    If stage A PRODUCES artifact X and stage B CONSUMES X, then A flows to B.
    This reconstructs the end-to-end business workflow (including cross-domain
    hand-offs) purely from each stage's declared inputs/outputs.
    """
    producers: dict[str, list[str]] = defaultdict(list)
    consumers: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        if e.type == EdgeType.PRODUCES:
            producers[e.dst].append(e.src)
        elif e.type == EdgeType.CONSUMES:
            consumers[e.dst].append(e.src)

    added = 0
    seen: set[tuple[str, str]] = set()
    for artifact, prod_stages in producers.items():
        for p in prod_stages:
            for c in consumers.get(artifact, []):
                if p == c or (p, c) in seen:
                    continue
                seen.add((p, c))
                cross = (graph.nodes[p].domain != graph.nodes[c].domain)
                graph.add_edge(Edge(
                    EdgeType.FLOWS_TO, p, c,
                    attributes={"via": artifact.split(".", 1)[1],
                                "cross_domain": cross},
                    confidence=Confidence.CONFIRMED, source=Source.STATIC,
                ))
                added += 1
    return added


def _emit_journey(graph: Graph, spec: dict, dangling: list[str]) -> None:
    """Emit the business-view spine: a Journey node + NEXT edges.

    Supports two shapes:
      * linear   `steps: [ {stage, phase}, ... ]`            (implicit a->b->c)
      * branching `flow:  [ {stage, phase, next: [ids]}, ]`  (a DAG that fans
        out and merges — the real, continuous business flow)
    """
    j = spec["journey"]
    jid = j["id"]
    _add_node(graph, jid, NodeType.JOURNEY, j["name"], summary=j.get("summary", ""))

    flow = j.get("flow")
    phase_of: dict[str, str | None] = {}

    def _stage(step):
        return step["stage"] if isinstance(step, dict) else step

    if flow:
        # First pass: register membership + phase.
        for i, step in enumerate(flow):
            sid = _stage(step)
            phase = step.get("phase") if isinstance(step, dict) else None
            phase_of[sid] = phase
            if sid not in graph.nodes:
                dangling.append(f"{jid}: flow references missing stage '{sid}'")
                continue
            graph.add_edge(Edge(
                EdgeType.CONTAINS, jid, sid,
                attributes={"step": i, "phase": phase} if phase else {"step": i},
            ))
        # Second pass: NEXT edges (branching/merging/continuous allowed).
        for step in flow:
            sid = _stage(step)
            nxts = step.get("next", []) if isinstance(step, dict) else []
            for tgt in nxts:
                if sid not in graph.nodes or tgt not in graph.nodes:
                    if tgt not in graph.nodes:
                        dangling.append(f"{jid}: NEXT references missing stage '{tgt}'")
                    continue
                graph.add_edge(Edge(
                    EdgeType.NEXT, sid, tgt,
                    attributes={"journey": jid, "phase": phase_of.get(tgt),
                                "branch": len(nxts) > 1,
                                "phase_change": phase_of.get(sid) != phase_of.get(tgt)},
                    confidence=Confidence.CONFIRMED, source=Source.STATIC,
                ))
        return

    prev: str | None = None
    prev_phase: str | None = None
    for i, step in enumerate(j.get("steps", [])):
        stage_id = _stage(step)
        phase = step.get("phase") if isinstance(step, dict) else None
        if stage_id not in graph.nodes:
            dangling.append(f"{jid}: step {i} references missing stage '{stage_id}'")
            continue
        graph.add_edge(Edge(
            EdgeType.CONTAINS, jid, stage_id,
            attributes={"step": i, "phase": phase} if phase else {"step": i},
        ))
        if prev is not None:
            graph.add_edge(Edge(
                EdgeType.NEXT, prev, stage_id,
                attributes={"journey": jid, "step": i, "phase": phase,
                            "phase_change": phase != prev_phase},
                confidence=Confidence.CONFIRMED, source=Source.STATIC,
            ))
        prev = stage_id
        prev_phase = phase


def _spec_directories(
    domains_dir: Path,
    journeys_dir: Path | None,
    shared_dir: Path | None,
) -> tuple[Path, Path, Path]:
    """Resolve either a domains directory or a curated-spec root.

    A custom ``<root>/domains`` automatically discovers sibling ``journeys``
    and ``shared`` directories. Explicit arguments still take precedence.
    """
    configured = Path(domains_dir)
    if (configured / "domains").is_dir():
        root = configured
        actual_domains = configured / "domains"
    else:
        actual_domains = configured
        root = configured.parent
    return (
        actual_domains,
        Path(journeys_dir) if journeys_dir is not None else root / "journeys",
        Path(shared_dir) if shared_dir is not None else root / "shared",
    )


def build(
    domains_dir: Path = DOMAINS_DIR,
    *,
    verbose: bool = False,
    journeys_dir: Path | None = None,
    shared_dir: Path | None = None,
) -> Graph:
    domains_dir, journeys_dir, shared_dir = _spec_directories(
        Path(domains_dir), journeys_dir, shared_dir
    )
    graph = Graph()
    # Shared sub-nodes first, so cross-domain references resolve to one node.
    shared_specs = load_shared_specs(shared_dir)
    for sspec in shared_specs:
        _emit_shared(graph, sspec)
    specs = load_domain_specs(domains_dir)
    for spec in specs:
        _emit_domain(graph, spec)
    dangling: list[str] = []
    for spec in specs:
        _emit_explicit_edges(graph, spec, dangling)
    flows = _derive_data_flow(graph)
    journeys = load_journey_specs(journeys_dir)
    for jspec in journeys:
        _emit_journey(graph, jspec, dangling)
    # Validate that shared sub-node references resolved to real nodes.
    for e in graph.edges:
        if e.type in (EdgeType.USES_SCHEMA, EdgeType.DOCUMENTED_BY, EdgeType.READS_CONFIG):
            if e.dst not in graph.nodes:
                dangling.append(f"shared ref {e.type.value} -> missing '{e.dst}'")
    if verbose:
        print(f"  loaded {len(shared_specs)} shared spec(s) (shared sub-nodes)")
        print(f"  derived {flows} FLOWS_TO edges from shared data artifacts")
        print(f"  loaded {len(journeys)} journey(s) (business-view spine)")
        if dangling:
            print("  ! dangling edge endpoints (will not traverse):")
            for d in sorted(set(dangling)):
                print(f"      {d}")
    return graph
