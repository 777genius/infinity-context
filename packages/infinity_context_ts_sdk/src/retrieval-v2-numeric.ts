export const RETRIEVAL_V2_WEIGHT_SCALE_MICROS = 1_000_000;
export const RETRIEVAL_V2_SCORE_SCALE_PICOS = 1_000_000_000_000;
export const RETRIEVAL_V2_MAX_PREFERENCE_BOOST_MICROS = 250_000;

/** Exact non-negative integer division using round-to-nearest, ties-to-even. */
export function roundHalfEvenDivide(numerator: bigint, denominator: bigint): bigint {
  if (numerator < 0n || denominator <= 0n) {
    throw new RangeError("roundHalfEvenDivide requires a non-negative numerator and positive denominator");
  }
  let quotient = numerator / denominator;
  const twiceRemainder = (numerator % denominator) * 2n;
  if (twiceRemainder > denominator || (twiceRemainder === denominator && quotient % 2n !== 0n)) {
    quotient += 1n;
  }
  return quotient;
}

/** Canonical weighted-RRF contribution in integer picos with BigInt products. */
export function retrievalV2ContributionScorePicos(
  providerWeightMicros: number,
  queryWeightMicros: number,
  totalQueryWeightMicros: number,
  providerRank: number,
): number {
  for (const [value, name] of [
    [providerWeightMicros, "providerWeightMicros"],
    [queryWeightMicros, "queryWeightMicros"],
    [totalQueryWeightMicros, "totalQueryWeightMicros"],
    [providerRank, "providerRank"],
  ] as const) {
    if (!Number.isSafeInteger(value) || value <= 0) throw new RangeError(`${name} must be a positive safe integer`);
  }
  const numerator = BigInt(providerWeightMicros) * BigInt(queryWeightMicros) * 1_000_000n;
  const denominator = BigInt(totalQueryWeightMicros) * BigInt(60 + providerRank);
  return safeBigInt(roundHalfEvenDivide(numerator, denominator), "contribution_score_picos");
}

export function retrievalV2PreferenceScores(
  baseScorePicos: number,
  requestedWeightMicros: number,
  matchedWeightMicros: number,
): { preferenceScoreMicros: number; preferenceBoostMicros: number; rerankScorePicos: number } {
  const base = checkedNonNegative(baseScorePicos, "baseScorePicos");
  const requested = checkedNonNegative(requestedWeightMicros, "requestedWeightMicros");
  const matched = checkedNonNegative(matchedWeightMicros, "matchedWeightMicros");
  if (matched > requested) throw new RangeError("matchedWeightMicros cannot exceed requestedWeightMicros");
  const preference = requested === 0n ? 0n : matched * 1_000_000n / requested;
  const boost = preference * 250_000n / 1_000_000n;
  const rerank = base * (1_000_000n + boost) / 1_000_000n;
  return {
    preferenceScoreMicros: safeBigInt(preference, "preference_score_micros"),
    preferenceBoostMicros: safeBigInt(boost, "preference_boost_micros"),
    rerankScorePicos: safeBigInt(rerank, "rerank_score_picos"),
  };
}

function checkedNonNegative(value: number, name: string): bigint {
  if (!Number.isSafeInteger(value) || value < 0) throw new RangeError(`${name} must be a non-negative safe integer`);
  return BigInt(value);
}

function safeBigInt(value: bigint, name: string): number {
  if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw new RangeError(`${name} exceeds the safe JSON integer range`);
  return Number(value);
}
