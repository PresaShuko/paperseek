import type {
  CitationEdgeOutput,
  CitationMapOutput,
  CitationNodeOutput,
  DiagnosticCheckOutput,
  DiagnosticOutput,
  DiagnosticSubmission as GeneratedDiagnosticSubmission,
  PersistedEvent,
  ResultOutput,
  ResultPageOutput,
  RunAudit as GeneratedRunAudit,
  RunDetail as GeneratedRunDetail,
  RunStatus as GeneratedRunStatus,
  RunSubmission,
  SourceDescriptorOutput,
} from "./generated";

export type RunStatus = GeneratedRunStatus;
export type SourceDescriptor = SourceDescriptorOutput;
export type RunDetail = GeneratedRunDetail;
export type RunEvent = PersistedEvent;
export type RunAudit = GeneratedRunAudit;
export type PaperResult = ResultOutput;
export type ResultPage = ResultPageOutput;
export type CitationNode = CitationNodeOutput;
export type CitationEdge = CitationEdgeOutput;
export type CitationMap = CitationMapOutput;
export type SearchSubmission = RunSubmission;
export type DiagnosticSubmission = GeneratedDiagnosticSubmission;
export type DiagnosticCheck = DiagnosticCheckOutput;
export type DiagnosticResult = DiagnosticOutput;
