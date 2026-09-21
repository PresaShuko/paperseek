import type { DiagnosticCheck } from "../../api/types";

type TFunc = (key: string) => string;

interface DiagnosticContext {
  source: string;
  sourceLabel: string;
  llmProvider: string;
  sourceName: (value: string, fallback?: string) => string;
  providerName: (value: string) => string;
}

export function diagnosticSummary(t: TFunc, context: DiagnosticContext, check: DiagnosticCheck): string {
  const passed = check.status === "pass";
  const failed = check.status === "fail";
  if (check.id === "source.supported") {
    return `${context.sourceName(context.source, context.sourceLabel)} ${t(passed ? "diagnosticSourceSupported" : "diagnosticSourceUnsupported")}`;
  }
  if (check.id === "source.credentials") {
    return t(failed
      ? "diagnosticSourceCredentialRequired"
      : check.status === "warning"
        ? "diagnosticSourceCredentialMissing"
        : "diagnosticSourceCredentialSatisfied");
  }
  if (check.id === "source.status") {
    return `${context.sourceName(context.source, context.sourceLabel)} ${t("diagnosticSourceUnavailable")}`;
  }
  if (check.id === "llm.provider") {
    return `${context.providerName(context.llmProvider)} ${t(passed ? "diagnosticProviderSupported" : "diagnosticProviderUnsupported")}`;
  }
  if (check.id === "llm.api_type") return t(passed ? "diagnosticApiTypeSupported" : "diagnosticApiTypeUnsupported");
  if (check.id === "llm.api_key") return t(passed ? "diagnosticLlmCredentialSatisfied" : "diagnosticLlmCredentialRequired");
  if (check.id === "llm.base_url") return t(`diagnosticBaseUrl${check.status === "pass" ? "Pass" : check.status === "warning" ? "Warning" : "Fail"}`);
  if (check.id.startsWith("retrieval.")) return t(`diagnosticRetrieval${check.status === "pass" ? "Pass" : check.status === "warning" ? "Warning" : "Fail"}`);
  return t(`diagnosticCheck${check.status === "pass" ? "Pass" : check.status === "warning" ? "Warning" : "Fail"}`);
}

export function diagnosticActions(t: TFunc, check: DiagnosticCheck): string[] {
  if (!check.actions.length) return [];
  if (check.id === "source.supported" || check.id === "source.status") return [t("actionChooseSource")];
  if (check.id === "source.credentials") return [t("actionConfigureSourceCredential")];
  if (check.id === "llm.provider") return [t("actionChooseProvider")];
  if (check.id === "llm.api_type") return [t("actionChooseApiType")];
  if (check.id === "llm.api_key") return [t("actionConfigureLlmCredential")];
  if (check.id === "llm.base_url") return [t("actionCorrectEndpoint")];
  if (check.id.startsWith("retrieval.")) return [t("actionCompleteRetrieval")];
  return [];
}
