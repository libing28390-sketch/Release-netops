import { copilotCopy } from './AssistantTab.copy';

/**
 * Knowledge-base miss handling on the Copilot page.
 *
 * When local retrieval returns nothing the server either answers locally
 * (deterministic "no match" text) or, if the security gateway allows it,
 * lets the model give a general reference that is explicitly unverified.
 * The answer text alone did not tell the user which of the two happened.
 */

export interface KnowledgeNoticeInput {
  retrievalStatus?: string | null;
  knowledgeFallback?: string | null;
  executionMode?: string | null;
}

export function knowledgeNoMatchNotice({ retrievalStatus, knowledgeFallback, executionMode }: KnowledgeNoticeInput): string | null {
  if (retrievalStatus !== 'no_match') return null;
  if (knowledgeFallback === 'cloud_web_reference') return copilotCopy.noMatchWebReference;
  if (knowledgeFallback === 'cloud_general_reference' || executionMode === 'provider_generated') {
    return copilotCopy.noMatchCloudReference;
  }
  return copilotCopy.noMatchLocal;
}

/**
 * Whether the model was skipped for this answer (debug panel "未调用").
 * A knowledge miss alone does not mean that: the model may still have
 * produced a general reference.  Only a clarification, or a miss answered
 * locally without any model route, skips the model.
 */
export function modelWasSkipped(input: { retrievalStatus?: string | null; executionMode?: string | null; routeModel?: string | null }): boolean {
  if (input.retrievalStatus === 'clarification_required') return true;
  if (input.retrievalStatus !== 'no_match') return false;
  if (input.executionMode === 'provider_generated' || input.routeModel) return false;
  return true;
}

/**
 * Retrieval counters for the debug panel.  Retrieval ran for "hit" and
 * "no_match", so a missing counter there means zero, not "not reported".
 */
export function retrievalCount(value: unknown, retrievalStatus?: string | null): string {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (retrievalStatus === 'no_match') return '0';
  return copilotCopy.notReported;
}
