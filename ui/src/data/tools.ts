import type { ToolDef } from '../types';

export const TOOL_CATALOG: ToolDef[] = [
  { id: 'calculate', label: 'Calculator', description: 'Basic math' },
  { id: 'set_reminder', label: 'Reminders', description: 'Set timers / reminders' },
  { id: 'online_search', label: 'Web search', description: 'Public web search' },
  { id: 'internal_search', label: 'Internal search', description: 'Private docs / knowledge base' },
];
