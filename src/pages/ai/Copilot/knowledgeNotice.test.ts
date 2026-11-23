import { describe, expect, it } from 'vitest';
import { copilotCopy } from './AssistantTab.copy';
import { knowledgeNoMatchNotice, modelWasSkipped, retrievalCount } from './knowledgeNotice';

describe('knowledge no-match notice', () => {
  it('says nothing when the knowledge base had a hit or did not run', () => {
    expect(knowledgeNoMatchNotice({ retrievalStatus: 'hit', executionMode: 'provider_generated' })).toBeNull();
    expect(knowledgeNoMatchNotice({ retrievalStatus: undefined })).toBeNull();
  });

  it('labels a model answer after a miss as unverified general reference', () => {
    expect(knowledgeNoMatchNotice({ retrievalStatus: 'no_match', knowledgeFallback: 'cloud_general_reference' })).toBe(copilotCopy.noMatchCloudReference);
    expect(knowledgeNoMatchNotice({ retrievalStatus: 'no_match', executionMode: 'provider_generated' })).toBe(copilotCopy.noMatchCloudReference);
  });

  it('labels web-backed and local answers after a miss', () => {
    expect(knowledgeNoMatchNotice({ retrievalStatus: 'no_match', knowledgeFallback: 'cloud_web_reference' })).toBe(copilotCopy.noMatchWebReference);
    expect(knowledgeNoMatchNotice({ retrievalStatus: 'no_match', executionMode: 'local_fallback' })).toBe(copilotCopy.noMatchLocal);
  });
});

describe('debug panel helpers', () => {
  it('does not claim the model was skipped when it answered a miss', () => {
    expect(modelWasSkipped({ retrievalStatus: 'no_match', executionMode: 'provider_generated' })).toBe(false);
    expect(modelWasSkipped({ retrievalStatus: 'no_match', routeModel: 'model-1' })).toBe(false);
    expect(modelWasSkipped({ retrievalStatus: 'no_match', executionMode: 'local_fallback' })).toBe(true);
    expect(modelWasSkipped({ retrievalStatus: 'clarification_required' })).toBe(true);
    expect(modelWasSkipped({ retrievalStatus: 'hit' })).toBe(false);
  });

  it('shows zero hits for a miss instead of "not reported"', () => {
    expect(retrievalCount(undefined, 'no_match')).toBe('0');
    expect(retrievalCount(0, 'no_match')).toBe('0');
    expect(retrievalCount(3, 'hit')).toBe('3');
    expect(retrievalCount(undefined, 'hit')).toBe(copilotCopy.notReported);
  });
});
