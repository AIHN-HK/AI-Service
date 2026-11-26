# Session Summary Prompt

Summarize the following conversation session.
Focus on user preferences, key decisions, and personal details found.
Merge it with the existing summary if provided.

## Input Format
- `existing_summary`: Current summary of the session (or "None" if empty)
- `recent_conversation`: List of the last N messages (role + content)

## Output Requirements
- Keep the summary concise (under 200 words)
- Focus on actionable insights about the user
- Preserve important context for future sessions
