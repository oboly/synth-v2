from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


VERSION = "2.0"
CYCLE_DAYS = 21.0
SUPPORTED_INTERVAL_CODE = "1d"
SELECTION_STATUS_UNIQUE = "UNIQUE_TOP_CANDIDATE"
SELECTION_STATUS_TIED = "TIED_TOP_CANDIDATES"

SENSITIVITY_TOLERANCE_HOURS: dict[str, float] = {
    "STRICT": 12.0,
    "NORMAL": 18.0,
    "MAX": 24.0,
}

DEFAULT_SHIFT_GRID_DAYS: tuple[float, ...] = (
    -10.5,
    -10.0,
    -9.0,
    -8.0,
    -7.0,
    -6.0,
    -5.0,
    -4.0,
    -3.0,
    -2.0,
    -1.0,
    0.0,
    1.0,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    8.0,
    9.0,
    10.0,
)


@dataclass(frozen=True)
class MarkerDefinition:
    ratio: float
    code: str
    kind: str
    marker_set: str


BASE_MARKERS: tuple[MarkerDefinition, ...] = (
    MarkerDefinition(0.236, "FIRST_LIFT_HIGH", "HIGH", "BASE"),
    MarkerDefinition(0.382, "FIRST_DIP_LOW", "LOW", "BASE"),
    MarkerDefinition(0.500, "SECOND_PEAK_RETEST_HIGH", "HIGH", "BASE"),
    MarkerDefinition(0.618, "SECOND_DIP_HIGHER_LOW", "LOW", "BASE"),
    MarkerDefinition(0.786, "IGNITION_PRE_SPIKE", "HIGH", "BASE"),
    MarkerDefinition(1.000, "MAIN_PULSE_TP_HIGH", "HIGH", "BASE"),
)

EXTENSION_MARKERS: tuple[MarkerDefinition, ...] = (
    MarkerDefinition(1.272, "EXTENSION_1.272", "HIGH", "EXTENSION"),
    MarkerDefinition(1.618, "EXTENSION_1.618", "HIGH", "EXTENSION"),
    MarkerDefinition(2.618, "EXTENSION_2.618", "HIGH", "EXTENSION"),
)


@dataclass(frozen=True)
class Candle:
    symbol: str
    open_ts_utc: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class MarkerEvidence:
    marker_set: str
    ratio: float
    code: str
    kind: str
    expected_ts_utc: str
    observed_candle_open_ts_utc: str | None
    observed_price: float | None
    residual_hours: float | None
    matched: bool


@dataclass(frozen=True)
class ShapeRuleDiagnostics:
    ranking_rules: dict[str, bool | None]
    diagnostic_rules: dict[str, bool | None]
    passed_count: int
    available_count: int
    reference_price: float


@dataclass(frozen=True)
class ShiftMatchResult:
    symbol: str
    raw_lattice_anchor_ts_utc: str
    interval_code: str
    sensitivity_mode: str
    tolerance_hours: float
    template_time_shift_days: float
    effective_schedule_origin_ts_utc: str
    matched_base_marker_count: int
    base_shape_rule_passed_count: int
    base_shape_rule_available_count: int
    max_base_marker_residual_hours: float
    total_base_marker_residual_hours: float
    base_marker_evidence: tuple[MarkerEvidence, ...]
    shape_rule_diagnostics: ShapeRuleDiagnostics
    extension_marker_evidence: tuple[MarkerEvidence, ...] = ()

    @property
    def ranking_key(self) -> tuple[int, int, float, float]:
        return (
            self.matched_base_marker_count,
            self.base_shape_rule_passed_count,
            -self.max_base_marker_residual_hours,
            -self.total_base_marker_residual_hours,
        )


@dataclass(frozen=True)
class ShiftSelectionSummary:
    symbol: str
    raw_lattice_anchor_ts_utc: str
    interval_code: str
    sensitivity_mode: str
    tolerance_hours: float
    selection_status: str
    selected_template_time_shift_days: float | None
    tied_shift_days: tuple[float, ...]
    ranked_candidates: tuple[ShiftMatchResult, ...]


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_supported_interval(interval_code: str) -> None:
    if interval_code != SUPPORTED_INTERVAL_CODE:
        raise ValueError(
            f"Unsupported interval_code={interval_code!r}; breathline lattice v2 supports only {SUPPORTED_INTERVAL_CODE!r}."
        )


def tolerance_hours_for_mode(mode: str) -> float:
    normalized = mode.strip().upper()
    if normalized not in SENSITIVITY_TOLERANCE_HOURS:
        raise ValueError(f"Unsupported sensitivity mode: {mode}")
    return SENSITIVITY_TOLERANCE_HOURS[normalized]


def candle_end_ts_utc(candle: Candle, interval_code: str) -> datetime:
    ensure_supported_interval(interval_code)
    return candle.open_ts_utc + timedelta(days=1)


def calculate_candle_residual_hours(expected_ts_utc: datetime, candle: Candle, interval_code: str) -> float:
    start = candle.open_ts_utc
    end = candle_end_ts_utc(candle, interval_code)
    if start <= expected_ts_utc < end:
        return 0.0
    if expected_ts_utc < start:
        return round((start - expected_ts_utc).total_seconds() / 3600.0, 6)
    return round((expected_ts_utc - end).total_seconds() / 3600.0, 6)


def expected_marker_ts(
    raw_lattice_anchor_ts_utc: datetime,
    template_time_shift_days: float,
    cycle_days: float,
    ratio: float,
) -> datetime:
    return raw_lattice_anchor_ts_utc + timedelta(days=template_time_shift_days + (cycle_days * ratio))


def effective_schedule_origin_ts(
    raw_lattice_anchor_ts_utc: datetime,
    template_time_shift_days: float,
) -> datetime:
    return raw_lattice_anchor_ts_utc + timedelta(days=template_time_shift_days)


def gt(a: float | None, b: float | None, tolerance_pct: float = 0.0) -> bool | None:
    if a is None or b is None:
        return None
    return a > b * (1.0 - tolerance_pct)


def lt(a: float | None, b: float | None, tolerance_pct: float = 0.0) -> bool | None:
    if a is None or b is None:
        return None
    return a < b * (1.0 + tolerance_pct)


def _observed_price(candle: Candle, kind: str) -> float:
    return candle.low if kind == "LOW" else candle.high


def _reference_price(candles: list[Candle], schedule_origin_ts_utc: datetime) -> float:
    idx = bisect.bisect_right(candles, schedule_origin_ts_utc, key=lambda c: c.open_ts_utc) - 1
    if idx >= 0:
        return candles[idx].close
    return candles[0].close


def _price_by_code(evidence: tuple[MarkerEvidence, ...], code: str) -> float | None:
    for row in evidence:
        if row.code == code and row.matched:
            return row.observed_price
    return None


def evaluate_shape_rules(
    candles: list[Candle],
    schedule_origin_ts_utc: datetime,
    evidence: tuple[MarkerEvidence, ...],
) -> ShapeRuleDiagnostics:
    reference_price = _reference_price(candles, schedule_origin_ts_utc)
    first_high = _price_by_code(evidence, "FIRST_LIFT_HIGH")
    first_low = _price_by_code(evidence, "FIRST_DIP_LOW")
    second_high = _price_by_code(evidence, "SECOND_PEAK_RETEST_HIGH")
    second_low = _price_by_code(evidence, "SECOND_DIP_HIGHER_LOW")
    ignition = _price_by_code(evidence, "IGNITION_PRE_SPIKE")
    pulse = _price_by_code(evidence, "MAIN_PULSE_TP_HIGH")

    ranking_rules: dict[str, bool | None] = {
        "first_lift_above_origin_reference": gt(first_high, reference_price),
        "first_dip_below_first_lift": lt(first_low, first_high),
        "second_peak_above_first_dip": gt(second_high, first_low),
        "second_dip_below_second_peak": lt(second_low, second_high),
        "second_dip_higher_than_first_dip": gt(second_low, first_low),
        "ignition_above_second_dip": gt(ignition, second_low),
        "pulse_above_ignition": gt(pulse, ignition),
        "pulse_above_second_peak": gt(pulse, second_high),
    }
    diagnostic_rules = {
        "second_peak_retests_first_lift_within_2p5pct": gt(second_high, first_high, 0.025),
    }
    available_count = sum(1 for value in ranking_rules.values() if value is not None)
    passed_count = sum(1 for value in ranking_rules.values() if value is True)
    return ShapeRuleDiagnostics(
        ranking_rules=ranking_rules,
        diagnostic_rules=diagnostic_rules,
        passed_count=passed_count,
        available_count=available_count,
        reference_price=reference_price,
    )


def _candidate_indices(
    candles: list[Candle],
    marker: MarkerDefinition,
    expected_ts_utc: datetime,
    tolerance_hours: float,
    interval_code: str,
    used_indices: set[int],
    prev_index: int,
) -> list[int]:
    # Candles are sorted by open_ts_utc. A candle qualifies if its residual <=
    # tolerance_hours. For 1d candles the residual window maps to:
    #   open_ts_utc >= expected - tolerance - 1d  (candle that ends within tolerance)
    #   open_ts_utc <= expected + tolerance        (candle that starts within tolerance)
    # Binary-search for the lower bound instead of scanning all candles.
    tolerance = timedelta(hours=tolerance_hours)
    window_lo = expected_ts_utc - tolerance - timedelta(days=1)
    window_hi = expected_ts_utc + tolerance
    lo_idx = bisect.bisect_left(candles, window_lo, key=lambda c: c.open_ts_utc)
    start = max(lo_idx, prev_index + 1)
    candidates: list[tuple[float, int]] = []
    for index in range(start, len(candles)):
        candle = candles[index]
        if candle.open_ts_utc > window_hi:
            break
        if index in used_indices:
            continue
        residual = calculate_candle_residual_hours(expected_ts_utc, candle, interval_code)
        if residual <= tolerance_hours:
            candidates.append((residual, index))
    candidates.sort(key=lambda item: (item[0], item[1]))
    return [index for _, index in candidates]


def _build_marker_evidence(
    markers: tuple[MarkerDefinition, ...],
    assignments: tuple[int | None, ...],
    candles: list[Candle],
    expected_ts_list: tuple[datetime, ...],
) -> tuple[MarkerEvidence, ...]:
    rows: list[MarkerEvidence] = []
    for marker, assignment, expected_ts_utc in zip(markers, assignments, expected_ts_list):
        if assignment is None:
            rows.append(
                MarkerEvidence(
                    marker_set=marker.marker_set,
                    ratio=marker.ratio,
                    code=marker.code,
                    kind=marker.kind,
                    expected_ts_utc=iso_utc(expected_ts_utc),
                    observed_candle_open_ts_utc=None,
                    observed_price=None,
                    residual_hours=None,
                    matched=False,
                )
            )
            continue
        candle = candles[assignment]
        rows.append(
            MarkerEvidence(
                marker_set=marker.marker_set,
                ratio=marker.ratio,
                code=marker.code,
                kind=marker.kind,
                expected_ts_utc=iso_utc(expected_ts_utc),
                observed_candle_open_ts_utc=iso_utc(candle.open_ts_utc),
                observed_price=_observed_price(candle, marker.kind),
                residual_hours=calculate_candle_residual_hours(expected_ts_utc, candle, SUPPORTED_INTERVAL_CODE),
                matched=True,
            )
        )
    return tuple(rows)


def _residual_metrics(evidence: tuple[MarkerEvidence, ...]) -> tuple[int, float, float]:
    matched = [row.residual_hours for row in evidence if row.matched and row.residual_hours is not None]
    if not matched:
        return 0, 0.0, 0.0
    return len(matched), max(matched), round(sum(matched), 6)


def _assignment_signature(assignments: tuple[int | None, ...]) -> tuple[int, ...]:
    return tuple(999999 if value is None else value for value in assignments)


def _shape_passed_count(prices: dict[str, float], ref_price: float) -> int:
    first_high = prices.get("FIRST_LIFT_HIGH")
    first_low = prices.get("FIRST_DIP_LOW")
    second_high = prices.get("SECOND_PEAK_RETEST_HIGH")
    second_low = prices.get("SECOND_DIP_HIGHER_LOW")
    ignition = prices.get("IGNITION_PRE_SPIKE")
    pulse = prices.get("MAIN_PULSE_TP_HIGH")
    return sum(
        1
        for v in (
            gt(first_high, ref_price),
            lt(first_low, first_high),
            gt(second_high, first_low),
            lt(second_low, second_high),
            gt(second_low, first_low),
            gt(ignition, second_low),
            gt(pulse, ignition),
            gt(pulse, second_high),
        )
        if v is True
    )


def _best_base_assignments(
    candles: list[Candle],
    raw_lattice_anchor_ts_utc: datetime,
    template_time_shift_days: float,
    cycle_days: float,
    tolerance_hours: float,
    interval_code: str,
) -> tuple[MarkerEvidence, ...]:
    expected_ts_list = tuple(
        expected_marker_ts(raw_lattice_anchor_ts_utc, template_time_shift_days, cycle_days, marker.ratio)
        for marker in BASE_MARKERS
    )
    schedule_origin_ts_utc = effective_schedule_origin_ts(raw_lattice_anchor_ts_utc, template_time_shift_days)
    # Compute reference price once — it is constant for this shift.
    ref_price = _reference_price(candles, schedule_origin_ts_utc)
    best_assignments: tuple[int | None, ...] | None = None
    best_key: tuple[int, int, float, float] | None = None
    best_signature: tuple[int, ...] | None = None

    def search(index: int, prev_index: int, used_indices: set[int], assignments: list[int | None]) -> None:
        nonlocal best_assignments, best_key, best_signature

        if index == len(BASE_MARKERS):
            # Compute ranking key without building MarkerEvidence to avoid iso_utc overhead.
            prices: dict[str, float] = {}
            residuals: list[float] = []
            for i, (assign, marker) in enumerate(zip(assignments, BASE_MARKERS)):
                if assign is not None:
                    prices[marker.code] = _observed_price(candles[assign], marker.kind)
                    residuals.append(
                        calculate_candle_residual_hours(expected_ts_list[i], candles[assign], interval_code)
                    )
            matched_count = len(residuals)
            max_residual = max(residuals) if residuals else 0.0
            total_residual = round(sum(residuals), 6)
            shape_passed = _shape_passed_count(prices, ref_price)
            key = (matched_count, shape_passed, -max_residual, -total_residual)
            signature = _assignment_signature(tuple(assignments))
            if best_key is None or key > best_key or (key == best_key and signature < (best_signature or signature)):
                best_assignments = tuple(assignments)
                best_key = key
                best_signature = signature
            return

        marker = BASE_MARKERS[index]
        expected_ts_utc = expected_ts_list[index]
        candidate_indices = _candidate_indices(
            candles=candles,
            marker=marker,
            expected_ts_utc=expected_ts_utc,
            tolerance_hours=tolerance_hours,
            interval_code=interval_code,
            used_indices=used_indices,
            prev_index=prev_index,
        )

        assignments.append(None)
        search(index + 1, prev_index, used_indices, assignments)
        assignments.pop()

        for candidate_index in candidate_indices:
            assignments.append(candidate_index)
            used_indices.add(candidate_index)
            search(index + 1, candidate_index, used_indices, assignments)
            used_indices.remove(candidate_index)
            assignments.pop()

    search(0, -1, set(), [])
    if best_assignments is None:
        best_assignments = tuple(None for _ in BASE_MARKERS)
    return _build_marker_evidence(BASE_MARKERS, best_assignments, candles, expected_ts_list)


def _best_extension_assignments(
    candles: list[Candle],
    raw_lattice_anchor_ts_utc: datetime,
    template_time_shift_days: float,
    cycle_days: float,
    tolerance_hours: float,
    interval_code: str,
    base_evidence: tuple[MarkerEvidence, ...],
) -> tuple[MarkerEvidence, ...]:
    used_indices = {
        index
        for index, row in enumerate(base_evidence)
        if row.matched and row.observed_candle_open_ts_utc is not None
    }
    used_candle_indices = {
        candle_index
        for candle_index, candle in enumerate(candles)
        if iso_utc(candle.open_ts_utc) in {row.observed_candle_open_ts_utc for row in base_evidence if row.matched}
    }
    prev_index = -1
    matched_base_indices = [
        candle_index
        for candle_index, candle in enumerate(candles)
        if iso_utc(candle.open_ts_utc) in {row.observed_candle_open_ts_utc for row in base_evidence if row.matched}
    ]
    if matched_base_indices:
        prev_index = max(matched_base_indices)

    expected_ts_list = tuple(
        expected_marker_ts(raw_lattice_anchor_ts_utc, template_time_shift_days, cycle_days, marker.ratio)
        for marker in EXTENSION_MARKERS
    )
    best_assignments: tuple[int | None, ...] | None = None
    best_key: tuple[int, float, float] | None = None
    best_signature: tuple[int, ...] | None = None

    def search(index: int, current_prev_index: int, assignments: list[int | None], current_used: set[int]) -> None:
        nonlocal best_assignments, best_key, best_signature

        if index == len(EXTENSION_MARKERS):
            assignment_tuple = tuple(assignments)
            evidence = _build_marker_evidence(EXTENSION_MARKERS, assignment_tuple, candles, expected_ts_list)
            matched_count, max_residual, total_residual = _residual_metrics(evidence)
            key = (matched_count, -max_residual, -total_residual)
            signature = _assignment_signature(assignment_tuple)
            if best_key is None or key > best_key or (key == best_key and signature < (best_signature or signature)):
                best_assignments = assignment_tuple
                best_key = key
                best_signature = signature
            return

        marker = EXTENSION_MARKERS[index]
        expected_ts_utc = expected_ts_list[index]
        candidate_indices = _candidate_indices(
            candles=candles,
            marker=marker,
            expected_ts_utc=expected_ts_utc,
            tolerance_hours=tolerance_hours,
            interval_code=interval_code,
            used_indices=current_used,
            prev_index=current_prev_index,
        )

        assignments.append(None)
        search(index + 1, current_prev_index, assignments, current_used)
        assignments.pop()

        for candidate_index in candidate_indices:
            assignments.append(candidate_index)
            current_used.add(candidate_index)
            search(index + 1, candidate_index, assignments, current_used)
            current_used.remove(candidate_index)
            assignments.pop()

    search(0, prev_index, [], set(used_candle_indices))
    if best_assignments is None:
        best_assignments = tuple(None for _ in EXTENSION_MARKERS)
    return _build_marker_evidence(EXTENSION_MARKERS, best_assignments, candles, expected_ts_list)


def evaluate_shift_candidate(
    candles: list[Candle],
    symbol: str,
    raw_lattice_anchor_ts_utc: datetime,
    sensitivity_mode: str,
    template_time_shift_days: float,
    *,
    cycle_days: float = CYCLE_DAYS,
    interval_code: str = SUPPORTED_INTERVAL_CODE,
    tolerance_hours: float | None = None,
) -> ShiftMatchResult:
    ensure_supported_interval(interval_code)
    normalized_mode = sensitivity_mode.strip().upper()
    resolved_tolerance = tolerance_hours_for_mode(normalized_mode) if tolerance_hours is None else tolerance_hours
    base_evidence = _best_base_assignments(
        candles=candles,
        raw_lattice_anchor_ts_utc=raw_lattice_anchor_ts_utc,
        template_time_shift_days=template_time_shift_days,
        cycle_days=cycle_days,
        tolerance_hours=resolved_tolerance,
        interval_code=interval_code,
    )
    matched_count, max_residual, total_residual = _residual_metrics(base_evidence)
    schedule_origin_ts_utc = effective_schedule_origin_ts(raw_lattice_anchor_ts_utc, template_time_shift_days)
    shape = evaluate_shape_rules(candles, schedule_origin_ts_utc, base_evidence)
    return ShiftMatchResult(
        symbol=symbol,
        raw_lattice_anchor_ts_utc=iso_utc(raw_lattice_anchor_ts_utc),
        interval_code=interval_code,
        sensitivity_mode=normalized_mode,
        tolerance_hours=resolved_tolerance,
        template_time_shift_days=template_time_shift_days,
        effective_schedule_origin_ts_utc=iso_utc(schedule_origin_ts_utc),
        matched_base_marker_count=matched_count,
        base_shape_rule_passed_count=shape.passed_count,
        base_shape_rule_available_count=shape.available_count,
        max_base_marker_residual_hours=max_residual,
        total_base_marker_residual_hours=total_residual,
        base_marker_evidence=base_evidence,
        shape_rule_diagnostics=shape,
    )


def attach_extension_evidence(
    candidate: ShiftMatchResult,
    candles: list[Candle],
    *,
    cycle_days: float = CYCLE_DAYS,
) -> ShiftMatchResult:
    extension_evidence = _best_extension_assignments(
        candles=candles,
        raw_lattice_anchor_ts_utc=parse_dt(candidate.raw_lattice_anchor_ts_utc),
        template_time_shift_days=candidate.template_time_shift_days,
        cycle_days=cycle_days,
        tolerance_hours=candidate.tolerance_hours,
        interval_code=candidate.interval_code,
        base_evidence=candidate.base_marker_evidence,
    )
    return ShiftMatchResult(
        symbol=candidate.symbol,
        raw_lattice_anchor_ts_utc=candidate.raw_lattice_anchor_ts_utc,
        interval_code=candidate.interval_code,
        sensitivity_mode=candidate.sensitivity_mode,
        tolerance_hours=candidate.tolerance_hours,
        template_time_shift_days=candidate.template_time_shift_days,
        effective_schedule_origin_ts_utc=candidate.effective_schedule_origin_ts_utc,
        matched_base_marker_count=candidate.matched_base_marker_count,
        base_shape_rule_passed_count=candidate.base_shape_rule_passed_count,
        base_shape_rule_available_count=candidate.base_shape_rule_available_count,
        max_base_marker_residual_hours=candidate.max_base_marker_residual_hours,
        total_base_marker_residual_hours=candidate.total_base_marker_residual_hours,
        base_marker_evidence=candidate.base_marker_evidence,
        shape_rule_diagnostics=candidate.shape_rule_diagnostics,
        extension_marker_evidence=extension_evidence,
    )


def select_best_shift(
    candles: list[Candle],
    symbol: str,
    raw_lattice_anchor_ts_utc: datetime,
    sensitivity_mode: str,
    *,
    cycle_days: float = CYCLE_DAYS,
    interval_code: str = SUPPORTED_INTERVAL_CODE,
    shift_grid_days: tuple[float, ...] = DEFAULT_SHIFT_GRID_DAYS,
) -> ShiftSelectionSummary:
    ensure_supported_interval(interval_code)
    normalized_mode = sensitivity_mode.strip().upper()
    candidates = [
        evaluate_shift_candidate(
            candles=candles,
            symbol=symbol,
            raw_lattice_anchor_ts_utc=raw_lattice_anchor_ts_utc,
            sensitivity_mode=normalized_mode,
            template_time_shift_days=shift_days,
            cycle_days=cycle_days,
            interval_code=interval_code,
        )
        for shift_days in shift_grid_days
    ]
    ranked = sorted(
        candidates,
        key=lambda row: (
            row.matched_base_marker_count,
            row.base_shape_rule_passed_count,
            -row.max_base_marker_residual_hours,
            -row.total_base_marker_residual_hours,
            -row.template_time_shift_days,
        ),
        reverse=True,
    )
    top = ranked[0]
    top_key = top.ranking_key
    tied_top = tuple(
        sorted(
            row.template_time_shift_days
            for row in ranked
            if row.ranking_key == top_key
        )
    )
    if len(tied_top) == 1:
        top = attach_extension_evidence(top, candles, cycle_days=cycle_days)
        ranked = [top if row.template_time_shift_days == top.template_time_shift_days else row for row in ranked]
        selection_status = SELECTION_STATUS_UNIQUE
        selected_shift = top.template_time_shift_days
    else:
        selection_status = SELECTION_STATUS_TIED
        selected_shift = None
    return ShiftSelectionSummary(
        symbol=symbol,
        raw_lattice_anchor_ts_utc=iso_utc(raw_lattice_anchor_ts_utc),
        interval_code=interval_code,
        sensitivity_mode=normalized_mode,
        tolerance_hours=tolerance_hours_for_mode(normalized_mode),
        selection_status=selection_status,
        selected_template_time_shift_days=selected_shift,
        tied_shift_days=tied_top,
        ranked_candidates=tuple(ranked),
    )
