import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import {
  retrievalV2ContributionScorePicos,
  retrievalV2PreferenceScores,
  roundHalfEvenDivide,
} from "../src/retrieval-v2-numeric.js";

const fixtureUrl = new URL("../fixtures/context_retrieval_v2/scoring_golden.json", import.meta.url);

describe("Retrieval V2 canonical integer scoring", () => {
  it("implements exact round-half-even division", () => {
    expect(roundHalfEvenDivide(1n, 2n)).toBe(0n);
    expect(roundHalfEvenDivide(3n, 2n)).toBe(2n);
    expect(roundHalfEvenDivide(5n, 2n)).toBe(2n);
    expect(roundHalfEvenDivide(7n, 2n)).toBe(4n);
  });

  it("matches every shared weighted-RRF contribution oracle", async () => {
    const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
    for (const item of fixture.contribution_cases) {
      expect(retrievalV2ContributionScorePicos(
        item.provider_weight_micros,
        item.query_weight_micros,
        item.total_query_weight_micros,
        item.provider_rank,
      ), item.case_id).toBe(item.contribution_score_picos);
    }
  });

  it("matches an independent JavaScript BigInt oracle, including valid half-even ties", async () => {
    const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
    const oracle = (item: any): bigint => {
      const numerator = BigInt(item.provider_weight_micros) * BigInt(item.query_weight_micros) * 1_000_000n;
      const denominator = BigInt(item.total_query_weight_micros) * BigInt(60 + item.provider_rank);
      const quotient = numerator / denominator;
      const doubledRemainder = (numerator % denominator) * 2n;
      return doubledRemainder > denominator ||
        (doubledRemainder === denominator && quotient % 2n === 1n)
        ? quotient + 1n
        : quotient;
    };
    expect(fixture.contribution_cases.map((item: any) => oracle(item).toString())).toEqual(
      fixture.contribution_cases.map((item: any) => String(item.contribution_score_picos)),
    );
    expect(fixture.contribution_cases.slice(0, 2).map((item: any) => item.case_id)).toEqual([
      "exact_half_even_down", "exact_half_even_up",
    ]);
  });

  it("matches every shared preference and rerank oracle", async () => {
    const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));
    for (const item of fixture.composite_cases) {
      const base = item.contribution_score_picos.reduce((total: number, value: number) => total + value, 0);
      const requested = item.source_requested_weight_micros + item.actor_requested_weight_micros + item.time_requested_weight_micros;
      const matched = item.source_matched_weight_micros + item.actor_matched_weight_micros + item.time_matched_weight_micros;
      expect(base, item.case_id).toBe(item.base_score_picos);
      expect(retrievalV2PreferenceScores(base, requested, matched), item.case_id).toEqual({
        preferenceScoreMicros: item.preference_score_micros,
        preferenceBoostMicros: item.preference_boost_micros,
        rerankScorePicos: item.rerank_score_picos,
      });
    }
  });

  it("uses BigInt before narrowing products to safe wire integers", () => {
    expect(retrievalV2ContributionScorePicos(10_000_000, 10_000_000, 10_000_000, 1))
      .toBe(163_934_426_230);
    expect(() => retrievalV2PreferenceScores(Number.MAX_SAFE_INTEGER, 1, 1)).toThrow();
  });

});
