/**
 * Phase A — Exploration test for cluster 1.1 (template enforcement) — Frontend.
 *
 * Vitest + fast-check property test for the ChangeOrderTab.tsx fallback branch:
 *   commandMode === 'template' && !scenarioId && devicePlatform != ''
 *
 * **Validates: Property 1 (design.md §Correctness Properties)**
 * **Requirements: 1.1, 1.2, 1.3**
 *
 * On UNFIXED code: the fallback branch synthesizes a payload with
 * `scenario_id: ''` and `platform: <devicePlatform>`. This test asserts
 * the FIXED expectation: the built payload does NOT carry
 * `scenario_id == devicePlatform` and `command_template` remains `{}`.
 *
 * EXPECTED OUTCOME on unfixed code: TEST FAILS (proves the bug exists).
 */
import { describe, it, expect } from 'vitest';
import * as fc from 'fast-check';

// ── Faithful port of the payload-building logic from ChangeOrderTab.tsx ──
// Lines ~1355–1395 of src/pages/ChangeOrderTab.tsx
interface BuildPayloadParams {
  commandMode: string;
  selectedScenarioId: string;
  effectiveScenarioPlatform: string;
  formTargetDevicePlatform: string;
  asDraft?: boolean;
}

function buildPayload({
  commandMode,
  selectedScenarioId,
  effectiveScenarioPlatform,
  formTargetDevicePlatform,
  asDraft = false,
}: BuildPayloadParams): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    status: asDraft ? 'draft' : 'initial_review',
    command_template: {},
    commands: [],
    rollback_plan: '',
  };

  if (commandMode === 'template' && selectedScenarioId && effectiveScenarioPlatform) {
    // Happy path: scenario selected with platform
    payload.command_template = {
      scenario_id: selectedScenarioId,
      source_kind: 'scenario',
      platform: effectiveScenarioPlatform,
      variables: {},
    };
  } else if (commandMode === 'template') {
    // BUG: Fallback branch — uses devicePlatform to synthesize empty template
    const devicePlatform = formTargetDevicePlatform || '';
    if (devicePlatform) {
      payload.command_template = {
        scenario_id: '',
        platform: devicePlatform,
        variables: {},
      };
    }
  }

  return payload;
}

// ── Property test ──────────────────────────────────────────────────────────

describe('ChangeOrderTab.tsx — cluster 1.1 template enforcement (frontend fallback)', () => {
  /**
   * **Validates: Property 1** — When commandMode === 'template' && !scenarioId
   * && devicePlatform != '', the built payload MUST NOT carry
   * scenario_id == devicePlatform (the task's explicit assertion) AND
   * command_template MUST remain {} (the fixed-behavior expectation).
   *
   * On UNFIXED code this test FAILS because the fallback branch synthesizes
   * {scenario_id: '', platform: devicePlatform, variables: {}}.
   */
  it('property: fallback branch does NOT silently build command_template payload', () => {
    const devicePlatforms = fc.constantFrom(
      'cisco_ios',
      'cisco_nxos',
      'huawei_vrp',
      'arista_eos',
      'juniper_junos',
      'h3c_comware',
    );

    fc.assert(
      fc.property(devicePlatforms, (devicePlatform: string) => {
        const payload = buildPayload({
          commandMode: 'template',
          selectedScenarioId: '',       // No scenario selected
          effectiveScenarioPlatform: '', // No effective platform
          formTargetDevicePlatform: devicePlatform, // Non-empty device platform
          asDraft: false,
        });

        const ct = payload.command_template as Record<string, unknown>;

        // Primary assertion from task: scenario_id must NOT equal devicePlatform
        expect(ct.scenario_id).not.toBe(devicePlatform);

        // Fixed-behavior assertion: command_template must remain empty {}
        expect(payload.command_template).toEqual({});
      }),
      { numRuns: 50 },
    );
  });
});
