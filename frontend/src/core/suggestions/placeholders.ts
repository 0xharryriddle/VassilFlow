export const SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN =
  /\[(?:主题|来源|topic|source)\]/i;

export function findSuggestionTemplatePlaceholder(
  text: string,
): { start: number; end: number } | null {
  const match = SUGGESTION_TEMPLATE_PLACEHOLDER_PATTERN.exec(text);
  if (!match) {
    return null;
  }

  return {
    start: match.index,
    end: match.index + match[0].length,
  };
}
