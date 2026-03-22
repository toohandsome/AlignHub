import { parseJsonArrayText, parseJsonObjectText } from "@/lib/json-form";

export function focusField(fieldName: string) {
  if (typeof document === "undefined") return;

  requestAnimationFrame(() => {
    const target = document.querySelector<HTMLElement>(`[name="${fieldName}"]`);
    if (!target) return;
    target.focus();
    target.scrollIntoView({ behavior: "smooth", block: "center" });
  });
}

export function getJsonObjectError(text: string, fieldLabel: string) {
  try {
    parseJsonObjectText(text, fieldLabel);
    return "";
  } catch (error) {
    return error instanceof Error ? error.message : `${fieldLabel} 格式不正确`;
  }
}

export function getJsonArrayError(text: string, fieldLabel: string) {
  try {
    parseJsonArrayText(text, fieldLabel);
    return "";
  } catch (error) {
    return error instanceof Error ? error.message : `${fieldLabel} 格式不正确`;
  }
}
