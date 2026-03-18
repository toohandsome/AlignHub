export function prettyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export function parseJsonObjectText(text: string, fieldName: string): Record<string, unknown> {
  const normalized = text.trim();
  if (!normalized) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(normalized);
  } catch (error) {
    throw new Error(`${fieldName} 必须是合法 JSON：${error instanceof Error ? error.message : String(error)}`);
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${fieldName} 必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

export function parseJsonArrayText(text: string, fieldName: string): unknown[] {
  const normalized = text.trim();
  if (!normalized) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(normalized);
  } catch (error) {
    throw new Error(`${fieldName} 必须是合法 JSON：${error instanceof Error ? error.message : String(error)}`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${fieldName} 必须是 JSON 数组`);
  }
  return parsed;
}
