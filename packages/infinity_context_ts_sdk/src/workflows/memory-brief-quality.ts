import type { ContextRetrievalComponent } from "../diagnostics.js";
import { InfinityContextError } from "../errors.js";
import type { JsonObject, SourceRef } from "../types.js";
import type { BuildMemoryBriefResult, MemoryBriefDiagnostics } from "./memory.js";
import {
  citationSourceRef,
  incrementCount,
  memoryBriefRetrievalHealthy,
  sourceRefKey,
} from "./workflow-helpers.js";

export interface MemoryBriefQualityPolicy {
  readonly minContextItems?: number;
  readonly requireSearch?: boolean;
  readonly minSearchItems?: number;
  readonly requireDigest?: boolean;
  readonly minDigestSections?: number;
  readonly minDigestSourceRefs?: number;
  readonly requireSupportedAnswer?: boolean;
  readonly requireDerivedRetrieval?: boolean;
  readonly requiredRetrieval?: readonly ContextRetrievalComponent[];
  readonly failOnWarnings?: boolean;
}

export interface MemoryBriefQualityMetrics {
  readonly contextItems: number;
  readonly contextSourceRefs: number;
  readonly topEvidenceItems: number;
  readonly searchItems: number;
  readonly digestSections: number;
  readonly digestSourceRefs: number;
}

export interface MemoryBriefQualityReport {
  readonly ok: boolean;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
  readonly metrics: MemoryBriefQualityMetrics;
  readonly retrieval: MemoryBriefDiagnostics;
}

export type MemoryBriefEvidenceSurface = "context" | "search" | "digest" | "top_evidence";

export interface MemoryBriefEvidenceSourceRef {
  readonly sourceType: string;
  readonly sourceId: string;
  readonly count: number;
  readonly surfaces: readonly MemoryBriefEvidenceSurface[];
}

export interface MemoryBriefEvidenceSummary {
  readonly contextItems: number;
  readonly searchItems: number;
  readonly digestSections: number;
  readonly topEvidenceItems: number;
  readonly sourceRefsTotal: number;
  readonly uniqueSourceRefs: number;
  readonly citationsTotal: number;
  readonly uniqueCitations: number;
  readonly bySourceType: Readonly<Record<string, number>>;
  readonly bySurface: Readonly<Record<MemoryBriefEvidenceSurface, number>>;
  readonly sourceRefs: readonly MemoryBriefEvidenceSourceRef[];
  readonly citationLabels: readonly string[];
  readonly missingSourceRefItemIds: readonly string[];
  readonly warnings: readonly string[];
}

interface MutableEvidenceSourceRef {
  readonly sourceType: string;
  readonly sourceId: string;
  count: number;
  readonly surfaces: Set<MemoryBriefEvidenceSurface>;
}

export function evaluateMemoryBriefQuality(
  brief: BuildMemoryBriefResult,
  policy: MemoryBriefQualityPolicy = {},
): MemoryBriefQualityReport {
  const errors: string[] = [];
  const warnings = [...brief.diagnostics.warnings];
  const metrics = memoryBriefQualityMetrics(brief);
  const minContextItems = policy.minContextItems ?? 1;
  const minSearchItems = policy.minSearchItems ?? 0;
  const minDigestSections = policy.minDigestSections ?? 0;
  const minDigestSourceRefs = policy.minDigestSourceRefs ?? 0;

  if (metrics.contextItems < minContextItems) {
    errors.push(`context returned ${metrics.contextItems} item(s), expected at least ${minContextItems}`);
  }
  if ((policy.requireSearch ?? false) && brief.search === undefined) {
    errors.push("search result is required");
  }
  if (brief.search !== undefined && metrics.searchItems < minSearchItems) {
    errors.push(`search returned ${metrics.searchItems} item(s), expected at least ${minSearchItems}`);
  }
  if ((policy.requireDigest ?? false) && brief.digest === undefined) {
    errors.push("digest result is required");
  }
  if (brief.digest !== undefined && metrics.digestSections < minDigestSections) {
    errors.push(`digest returned ${metrics.digestSections} section(s), expected at least ${minDigestSections}`);
  }
  if (brief.digest !== undefined && metrics.digestSourceRefs < minDigestSourceRefs) {
    errors.push(`digest returned ${metrics.digestSourceRefs} source ref(s), expected at least ${minDigestSourceRefs}`);
  }
  if ((policy.requireSupportedAnswer ?? true) && brief.context.data.answer_support.status !== "supported") {
    errors.push(`context answer support is ${brief.context.data.answer_support.status}`);
  }
  if ((policy.requireDerivedRetrieval ?? false) && !brief.diagnostics.derivedRetrievalUsed) {
    errors.push("derived retrieval was not used");
  }
  for (const component of policy.requiredRetrieval ?? []) {
    if (!memoryBriefRetrievalHealthy(brief.diagnostics, component)) {
      errors.push(`${component} retrieval is not healthy`);
    }
  }
  if ((policy.failOnWarnings ?? false) && warnings.length > 0) {
    errors.push(`brief returned ${warnings.length} warning(s)`);
  }

  return {
    ok: errors.length === 0,
    errors,
    warnings,
    metrics,
    retrieval: brief.diagnostics,
  };
}

export function assertMemoryBriefQuality(
  brief: BuildMemoryBriefResult,
  policy: MemoryBriefQualityPolicy = {},
): MemoryBriefQualityReport {
  const report = evaluateMemoryBriefQuality(brief, policy);
  if (report.ok) {
    return report;
  }

  throw new InfinityContextError({
    statusCode: 0,
    code: "memory.brief_quality_failed",
    message: `Memory brief quality failed: ${report.errors.join("; ")}`,
    retryable: false,
    details: {
      errors: report.errors,
      warnings: report.warnings,
      metrics: memoryBriefQualityMetricsDetails(report.metrics),
      retrieval: {
        derived_retrieval_used: report.retrieval.derivedRetrievalUsed,
        vector_healthy: report.retrieval.vectorHealthy,
        graph_healthy: report.retrieval.graphHealthy,
        rag_healthy: report.retrieval.ragHealthy,
        retrieval_sources_used: report.retrieval.retrievalSourcesUsed,
      },
    } satisfies JsonObject,
  });
}

export function summarizeMemoryBriefEvidence(brief: BuildMemoryBriefResult): MemoryBriefEvidenceSummary {
  const sourceRefs = new Map<string, MutableEvidenceSourceRef>();
  const citationLabels = new Set<string>();
  const missingSourceRefItemIds = new Set<string>();
  const bySourceType: Record<string, number> = {};
  const bySurface: Record<MemoryBriefEvidenceSurface, number> = {
    context: 0,
    search: 0,
    digest: 0,
    top_evidence: 0,
  };
  let citationsTotal = 0;
  let sourceRefsTotal = 0;

  const addSourceRef = (sourceRef: SourceRef, surface: MemoryBriefEvidenceSurface): void => {
    sourceRefsTotal += 1;
    bySurface[surface] += 1;
    incrementCount(bySourceType, sourceRef.source_type);
    const key = sourceRefKey(sourceRef);
    const existing = sourceRefs.get(key);
    if (existing === undefined) {
      sourceRefs.set(key, {
        sourceType: sourceRef.source_type,
        sourceId: sourceRef.source_id,
        count: 1,
        surfaces: new Set([surface]),
      });
      return;
    }

    existing.count += 1;
    existing.surfaces.add(surface);
  };

  const addCitation = (
    citation: { readonly label?: string; readonly citation_id?: string; readonly source_type?: string; readonly source_id?: string },
    surface: MemoryBriefEvidenceSurface,
  ): void => {
    citationsTotal += 1;
    const label = citation.label ?? citation.citation_id;
    if (label !== undefined && label.length > 0) {
      citationLabels.add(label);
    }
    const sourceRef = citationSourceRef(citation);
    if (sourceRef !== undefined) {
      addSourceRef(sourceRef, surface);
    }
  };

  const addItemEvidence = (
    item: {
      readonly item_id: string;
      readonly source_refs?: readonly SourceRef[];
      readonly citations?: readonly {
        readonly label?: string;
        readonly citation_id?: string;
        readonly source_type?: string;
        readonly source_id?: string;
      }[];
    },
    surface: MemoryBriefEvidenceSurface,
  ): void => {
    const itemSourceRefs = item.source_refs ?? [];
    const itemCitations = item.citations ?? [];
    for (const sourceRef of itemSourceRefs) {
      addSourceRef(sourceRef, surface);
    }
    for (const citation of itemCitations) {
      addCitation(citation, surface);
    }
    if (itemSourceRefs.length === 0 && itemCitations.length === 0) {
      missingSourceRefItemIds.add(item.item_id);
    }
  };

  for (const item of brief.context.data.items) {
    addItemEvidence(item, "context");
  }
  for (const evidence of brief.context.data.top_evidence) {
    if (evidence.item !== undefined) {
      addItemEvidence(evidence.item, "top_evidence");
    }
    if (evidence.citation !== undefined && evidence.citation !== null) {
      addCitation(evidence.citation, "top_evidence");
    }
  }
  for (const item of brief.search?.data.items ?? []) {
    addItemEvidence(item, "search");
  }
  for (const section of brief.digest?.data.sections ?? []) {
    for (const item of section.items) {
      addItemEvidence(item, "digest");
    }
  }
  for (const sourceRef of brief.digest?.data.source_refs ?? []) {
    addSourceRef(sourceRef, "digest");
  }

  return {
    contextItems: brief.context.data.items.length,
    searchItems: brief.search?.data.items.length ?? 0,
    digestSections: brief.digest?.data.sections.length ?? 0,
    topEvidenceItems: brief.context.data.top_evidence.length,
    sourceRefsTotal,
    uniqueSourceRefs: sourceRefs.size,
    citationsTotal,
    uniqueCitations: citationLabels.size,
    bySourceType,
    bySurface,
    sourceRefs: [...sourceRefs.values()]
      .map((sourceRef) => ({
        sourceType: sourceRef.sourceType,
        sourceId: sourceRef.sourceId,
        count: sourceRef.count,
        surfaces: [...sourceRef.surfaces].sort(),
      }))
      .sort((left, right) => right.count - left.count || left.sourceType.localeCompare(right.sourceType) ||
        left.sourceId.localeCompare(right.sourceId)),
    citationLabels: [...citationLabels].sort(),
    missingSourceRefItemIds: [...missingSourceRefItemIds].sort(),
    warnings: brief.context.data.answer_support.warnings,
  };
}

function memoryBriefQualityMetrics(brief: BuildMemoryBriefResult): MemoryBriefQualityMetrics {
  return {
    contextItems: brief.context.data.items.length,
    contextSourceRefs: countItemSourceRefs(brief.context.data.items),
    topEvidenceItems: brief.context.data.top_evidence.length,
    searchItems: brief.search?.data.items.length ?? 0,
    digestSections: brief.digest?.data.sections.length ?? 0,
    digestSourceRefs: brief.digest?.data.source_refs.length ?? 0,
  };
}

function memoryBriefQualityMetricsDetails(metrics: MemoryBriefQualityMetrics): JsonObject {
  return {
    context_items: metrics.contextItems,
    context_source_refs: metrics.contextSourceRefs,
    top_evidence_items: metrics.topEvidenceItems,
    search_items: metrics.searchItems,
    digest_sections: metrics.digestSections,
    digest_source_refs: metrics.digestSourceRefs,
  };
}

function countItemSourceRefs(items: readonly { readonly source_refs?: readonly SourceRef[] }[]): number {
  return items.reduce((total, item) => total + (item.source_refs?.length ?? 0), 0);
}
