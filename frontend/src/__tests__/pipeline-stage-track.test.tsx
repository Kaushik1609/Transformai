/**
 * Batch 2 — UI-5 Operational Pipeline Observer tests.
 *
 * Covers the pure `derivePipelineStages` mapping from real backend signals
 * (job.status / job.progress / job.source_id / outputs[]) to the six-stage
 * track (Load → Retrieve → Plan → Generate → Render → Validate), plus the
 * rendered PipelineStageTrack. Stages are derived from REAL data only — no
 * invented journal, no fabricated percentages.
 */
import { render, screen } from "@testing-library/react";
import { derivePipelineStages, PipelineStageTrack } from "@/components/results";
import type {
  OutputResponse,
  TransformationJobResponse,
} from "@/lib/api";

const STAGE_IDS = ["load", "retrieve", "plan", "generate", "render", "validate"];

const jobWith = (
  overrides: Partial<TransformationJobResponse>,
): TransformationJobResponse => ({
  id: "22222222-2222-2222-2222-222222222222",
  project_id: "11111111-1111-1111-1111-111111111111",
  source_id: "source",
  configuration_id: "config",
  requested_outputs: { output_types: ["summary"] },
  status: "queued",
  progress: 0,
  error_message: null,
  started_at: null,
  completed_at: null,
  created_at: "2025-01-01T00:00:00Z",
  ...overrides,
});

const completedOutput = (type = "summary"): OutputResponse => ({
  id: `out-${type}`,
  job_id: "22222222-2222-2222-2222-222222222222",
  output_type: type,
  status: "completed",
  structured_content: null,
  text_content: "Content.",
  storage_key: `artifacts/${type}.txt`,
  mime_type: "text/plain",
  output_metadata: null,
  created_at: "2025-01-01T00:01:00Z",
});

const failedOutput = (type = "video"): OutputResponse => ({
  id: `out-${type}`,
  job_id: "22222222-2222-2222-2222-222222222222",
  output_type: type,
  status: "failed",
  structured_content: null,
  text_content: null,
  storage_key: null,
  mime_type: null,
  output_metadata: null,
  created_at: "2025-01-01T00:01:00Z",
});

const statusOf = (job: TransformationJobResponse, outputs: OutputResponse[]) =>
  Object.fromEntries(
    derivePipelineStages(job, outputs).map((s) => [s.id, s.status]),
  );

describe("derivePipelineStages — honest stage mapping from backend signals", () => {
  it("maps a queued job to all-pending stages", () => {
    const stages = derivePipelineStages(jobWith({ status: "queued" }), []);
    expect(stages).toHaveLength(6);
    expect(stages.map((s) => s.id)).toEqual(STAGE_IDS);
    expect(stages.every((s) => s.status === "pending")).toBe(true);
    expect(stages[0].detail).toBe("Waiting to start");
  });

  it("maps a cancelled job to all-pending stages with a note", () => {
    const stages = derivePipelineStages(jobWith({ status: "cancelled" }), []);
    expect(stages.every((s) => s.status === "pending")).toBe(true);
    expect(stages[0].detail).toBe("Job cancelled");
  });

  it("maps running/progress 0 to Load running only (no invented progress)", () => {
    const job = jobWith({ status: "running", progress: 0, started_at: "2025-01-01T00:00:01Z" });
    const status = statusOf(job, []);
    expect(status.load).toBe("running");
    expect(status.retrieve).toBe("pending");
    expect(status.plan).toBe("pending");
    expect(status.generate).toBe("pending");
    expect(status.render).toBe("pending");
    expect(status.validate).toBe("pending");
  });

  it("maps running/progress>0 to Load/Retrieve/Plan completed and Generate running", () => {
    const job = jobWith({ status: "running", progress: 40 });
    const status = statusOf(job, [completedOutput()]);
    expect(status.load).toBe("completed");
    expect(status.retrieve).toBe("completed");
    expect(status.plan).toBe("completed");
    expect(status.generate).toBe("running");
    expect(status.render).toBe("pending");
    expect(status.validate).toBe("pending");
  });

  it("marks Retrieve as skipped when the job has no source", () => {
    const job = jobWith({ status: "running", progress: 40, source_id: null });
    expect(statusOf(job, [completedOutput()]).retrieve).toBe("skipped");
  });

  it("maps a completed job to all-completed stages", () => {
    const job = jobWith({ status: "completed", progress: 100 });
    const status = statusOf(job, [completedOutput()]);
    expect(status).toEqual({
      load: "completed",
      retrieve: "completed",
      plan: "completed",
      generate: "completed",
      render: "completed",
      validate: "completed",
    });
  });

  it("marks Generate failed when the job completed with failed outputs", () => {
    const job = jobWith({ status: "completed", progress: 100 });
    const status = statusOf(job, [completedOutput(), failedOutput()]);
    expect(status.generate).toBe("failed");
    expect(status.load).toBe("completed");
  });

  it("maps a load failure to Load failed and later stages pending", () => {
    const job = jobWith({
      status: "failed",
      progress: 100,
      error_message: "Canonical content could not be generated for this source.",
    });
    const status = statusOf(job, []);
    expect(status.load).toBe("failed");
    expect(status.retrieve).toBe("completed");
    expect(status.generate).toBe("pending");
  });

  it("maps a generation timeout to Generate failed with earlier stages completed", () => {
    const job = jobWith({
      status: "failed",
      progress: 100,
      error_message: "Ollama inference timed out.",
    });
    const status = statusOf(job, []);
    expect(status.load).toBe("completed");
    expect(status.retrieve).toBe("completed");
    expect(status.plan).toBe("completed");
    expect(status.generate).toBe("failed");
    expect(status.render).toBe("pending");
  });
});

describe("PipelineStageTrack", () => {
  it("renders all six stage rows with their status for a completed job", () => {
    render(
      <PipelineStageTrack
        job={jobWith({ status: "completed", progress: 100 })}
        outputs={[completedOutput()]}
      />,
    );

    expect(screen.getByRole("list", { name: "Pipeline stages" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    for (const label of ["Load", "Retrieve", "Plan", "Generate", "Render", "Validate"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // Completed stage status labels.
    expect(screen.getAllByText("Completed")).toHaveLength(6);
  });

  it("shows Load running without any fabricated percentage while progress is 0", () => {
    render(
      <PipelineStageTrack
        job={jobWith({ status: "running", progress: 0 })}
        outputs={[]}
      />,
    );

    expect(screen.getByText("Load")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText("Ingesting source")).toBeInTheDocument();
    // No percentage invented from per-stage knowledge that does not exist.
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
  });

  it("shows skipped Retrieve when a completed quick run had no source", () => {
    render(
      <PipelineStageTrack
        job={jobWith({ status: "completed", progress: 100, source_id: null })}
        outputs={[completedOutput()]}
      />,
    );

    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText("No source to retrieve")).toBeInTheDocument();
  });

  it("never invents progress details for later stages while running", () => {
    const job = jobWith({ status: "running", progress: 40 });
    render(<PipelineStageTrack job={job} outputs={[completedOutput()]} />);

    // Only Generate reports activity; Render/Validate stay pending and quiet.
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getAllByText("Pending")).toHaveLength(2);
    expect(screen.queryByText("Rendering 1 completed")).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
  });
});