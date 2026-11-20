export type TagBooleanOperator = 'and' | 'or';

export interface TagExpressionGroup {
  operator: TagBooleanOperator;
  negated: boolean;
  tag_ids: string[];
  groups: TagExpressionGroup[];
}

export interface LegacyTagConditionGroup {
  tag_ids: string[];
  operator?: 'and' | 'or' | 'not';
}

export interface TagFilterConfig {
  expression: TagExpressionGroup;
  /** Kept for callers that still hold an old in-memory filter. */
  groups: LegacyTagConditionGroup[];
  /** Kept for callers that still hold an old in-memory filter. */
  exclude_tag_ids: string[];
}

export const emptyTagExpression = (): TagExpressionGroup => ({
  operator: 'and',
  negated: false,
  tag_ids: [],
  groups: [],
});

export const EMPTY_TAG_FILTER: TagFilterConfig = {
  expression: emptyTagExpression(),
  groups: [],
  exclude_tag_ids: [],
};
