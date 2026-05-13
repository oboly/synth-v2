# A+ Table 1 Regime-Gate Validation v1

## Status

Research-only validation.

Scope:

- market-only
- account-agnostic
- no selection_engine changes
- no decision_gate changes
- no execution_planner changes
- no executor/order logic
- no broker calls
- no broker writes
- no order submission

## Purpose

Validate whether A+ canonical TABLE 1 labels add useful structure to Breath Curve regime-gated policy preview rows.

Primary question:

    Do A+ canonical core / avoid / anchor context labels improve interpretation of regime-gated Breath Curve candidates?

## Inputs

A+ canonical TABLE 1 raw snapshot:

    data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt

Breath Curve regime-gated policy preview rows:

    data/research/breath_curve_regime_gated_policy_preview_v1/*_policy_rows.csv

## A+ buckets

The runner derives:

    APLUS_CANONICAL_CORE
    APLUS_AVOID
    APLUS_ANCHOR_CONTEXT
    APLUS_CAUTION
    APLUS_OTHER
    APLUS_MISSING

Canonical core definition follows the Table 1 parser:

    structural_role = leader
    coherence = high
    geometry = clean or mixed
    expansion_quality = strong or moderate
    anchor_strength = strong or moderate
    strategic_bias = accumulation or continuation

## Important interpretation

This validation does not create strategy logic.

This validation does not promote A+ labels into selection_engine.

This validation does not connect A+ labels to decision_gate or execution.

The correct downstream path is:

    external A+ symbolic snapshot
    normalized research artifact
    validation report
    optional later market-only selection modifier proposal after repeated validation

## Current known conflict to inspect

FIL is a key conflict case:

    Breath Curve: core symbol / volume-expansion candidate
    A+ Table 1: avoid / late compression / distorted / laggard

This is not automatically wrong. It may indicate an explosive but structurally dirty candidate type.
