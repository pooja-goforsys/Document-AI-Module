/**
 * Extracts the "Related Questions" section from the tail of an AI response.
 *
 * The system prompt instructs the model to end every response with:
 *   ---
 *   **Related Questions:**
 *   - Question 1?
 *   - Question 2?
 *   - Question 3?
 *
 * Handles variations the model might produce:
 *   • "---" / "___" / "***" horizontal rules
 *   • **bold**, *italic*, or plain "Related Questions" header
 *   • "## Related Questions" heading format
 *   • Bullet markers: "-" or "*"
 */
const RELATED_SECTION_RE =
  /\n*(?:[-*_]{3,}\n+)?(?:#{1,3}\s*)?(?:\*{1,2})?Related Questions:?(?:\*{1,2})?\n+((?:[-*•]\s+.+\n?)+)/i

export function extractRelatedQuestions(content: string): {
  mainContent: string
  questions: string[]
} {
  const match = content.match(RELATED_SECTION_RE)
  if (!match || match.index === undefined) {
    return { mainContent: content, questions: [] }
  }

  const questions = match[1]
    .split('\n')
    .filter(line => /^[-*•]\s+/.test(line.trim()))
    .map(line => line.replace(/^[-*•]\s+/, '').trim())
    .filter(q => q.length > 2)

  const mainContent = content.slice(0, match.index).trimEnd()
  return { mainContent, questions }
}
