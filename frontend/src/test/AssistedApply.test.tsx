import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import AssistedApply from "../views/AssistedApply";
import { api, applicationsApi, ApiError } from "../api";
import type { ApplicationRow, ApplicationsBoard, Job, JobsPage, TailoredResume } from "../types";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
    applicationsApi: {
      board: vi.fn(),
      get: vi.fn(),
      create: vi.fn(),
      events: vi.fn(),
      setStatus: vi.fn(),
      confirmSubmit: vi.fn(),
      availability: vi.fn(),
    },
  };
});

const apiMock = vi.mocked(api);
const appApi = vi.mocked(applicationsApi);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    source: "adzuna",
    source_job_id: "100",
    title: "Backend Engineer",
    company: "ACME",
    location: "Dubai",
    description: "Python and SQL required.",
    employment_type: null,
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    is_remote: null,
    remote_policy: null,
    canonical_url: "https://jobs.example.com/100",
    original_url: "https://jobs.example.com/100",
    posted_at: null,
    is_active: true,
    is_expired: false,
    ...overrides,
  };
}

function tailored(overrides: Partial<TailoredResume> = {}): TailoredResume {
  return {
    id: "tr-1",
    resume_id: "cv-1",
    job_id: "job-1",
    version: 1,
    approval_status: "approved",
    content: {
      title: "Backend CV",
      sections: [
        {
          name: "Experience",
          items: [{ text: "Built APIs with Python", evidence_refs: ["experience:0"] }],
        },
      ],
    },
    unsupported_claims: [
      { section: "Experience", text: "Architected global platform", reason: "no CV evidence", evidence_refs: [] },
    ],
    final_pdf_path: null,
    approved_at: null,
    created_at: "2026-10-23T08:00:00Z",
    ...overrides,
  };
}

function appRow(overrides: Partial<ApplicationRow> = {}): ApplicationRow {
  return {
    id: "app-1",
    job_id: "job-1",
    status: "queued",
    notes: null,
    submitted_at: null,
    tailored_resume_id: null,
    created_at: "2026-10-23T08:00:00Z",
    updated_at: "2026-10-23T08:00:00Z",
    job_title: "Backend Engineer",
    job_company: "ACME",
    job_canonical_url: "https://jobs.example.com/100",
    job_is_active: true,
    job_is_expired: false,
    job_source: "adzuna",
    allowed_transitions: ["prepared", "withdrawn", "closed"],
    ...overrides,
  };
}

function setupLoad(
  jobsPage: JobsPage = { total: 1, items: [job()] },
  board: ApplicationsBoard = { items: [], counts: {} },
  rows: TailoredResume[] = [tailored()],
) {
  apiMock.get.mockImplementation((path: string) => {
    if (path === "/jobs") return Promise.resolve(jobsPage);
    if (path === "/tailored") return Promise.resolve(rows);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
  appApi.board.mockResolvedValue(board);
}

async function selectJob() {
  // Data loads asynchronously; wait for the picker before interacting.
  await screen.findByTestId("apply-picker");
  await userEvent.click(screen.getByTestId("apply-job-select"));
  await userEvent.selectOptions(screen.getByTestId("apply-job-select"), "job-1");
  await waitFor(() => screen.getByTestId("apply-job-review"));
}

describe("AssistedApply", () => {
  it("creates a tracking record with the selected job and tailored resume", async () => {
    setupLoad();
    appApi.create.mockResolvedValue(appRow({ tailored_resume_id: "tr-1" }));
    const onNavigate = vi.fn();
    render(<AssistedApply onNavigate={onNavigate} />);
    await selectJob();

    // Review content of the job before acting.
    expect(screen.getByTestId("apply-job-review")).toHaveTextContent("Backend Engineer");
    expect(screen.getByTestId("apply-job-review")).toHaveTextContent("Python and SQL required.");

    await userEvent.click(screen.getByTestId("apply-resume-select"));
    await userEvent.selectOptions(screen.getByTestId("apply-resume-select"), "tr-1");
    await waitFor(() => screen.getByTestId("apply-resume-review"));
    expect(screen.getByTestId("apply-resume-review")).toHaveTextContent("Built APIs with Python");
    expect(screen.getByTestId("apply-unsupported-claims")).toHaveTextContent("no CV evidence");

    await userEvent.click(screen.getByTestId("apply-create"));

    await waitFor(() => expect(appApi.create).toHaveBeenCalledWith("job-1", "tr-1"));
    await waitFor(() => expect(screen.getByTestId("apply-result")).toHaveTextContent("Queued"));
    await userEvent.click(screen.getByTestId("apply-open-tracking"));
    expect(onNavigate).toHaveBeenCalledWith("applications");
  });

  it("tells the user no tailored CV exists for the chosen job", async () => {
    setupLoad({ total: 1, items: [job()] }, { items: [], counts: {} }, []);
    render(<AssistedApply onNavigate={vi.fn()} />);
    await selectJob();
    const warning = screen.getByTestId("no-tailored-warning");
    expect(warning).toHaveTextContent("No tailored CV exists for this job");
    const button = screen.getByRole("button", { name: /go to tailored cv/i });
    await userEvent.click(button);
  });

  it("only lists tailored CVs matching the selected job", async () => {
    setupLoad(
      { total: 1, items: [job()] },
      { items: [], counts: {} },
      [tailored(), tailored({ id: "tr-2", job_id: "job-2", version: 2 })],
    );
    render(<AssistedApply onNavigate={vi.fn()} />);
    await screen.findByTestId("apply-picker");
    await userEvent.click(screen.getByTestId("apply-job-select"));
    await userEvent.selectOptions(screen.getByTestId("apply-job-select"), "job-1");
    await waitFor(() => screen.getByTestId("apply-resume-select"));
    const options = screen.getByTestId("apply-resume-select").querySelectorAll("option");
    const texts = Array.from(options).map((o) => o.textContent ?? "");
    expect(texts).toHaveLength(2); // placeholder + the one matching resume
    expect(texts.join(" | ")).toContain("v1");
    expect(texts.join(" | ")).not.toContain("v2");
  });

  it("warns that the job is already tracked and offers reuse", async () => {
    setupLoad(
      { total: 1, items: [job()] },
      { items: [appRow()], counts: { queued: 1 } },
      [tailored()],
    );
    appApi.create.mockResolvedValue(appRow());
    render(<AssistedApply onNavigate={vi.fn()} />);
    await selectJob();
    expect(screen.getByTestId("already-tracked")).toHaveTextContent("already tracked");
    const create = screen.getByTestId("apply-create");
    expect(create).toHaveTextContent("Reuse tracking record");
    await userEvent.click(create);
    await waitFor(() => expect(appApi.create).toHaveBeenCalledWith("job-1", undefined));
  });

  it("surfaces backend validation errors", async () => {
    setupLoad();
    appApi.create.mockRejectedValue(new ApiError(409, "tailored resume is associated with a different job"));
    render(<AssistedApply onNavigate={vi.fn()} />);
    await selectJob();
    await userEvent.click(screen.getByTestId("apply-resume-select"));
    await userEvent.selectOptions(screen.getByTestId("apply-resume-select"), "tr-1");
    await userEvent.click(screen.getByTestId("apply-create"));
    await waitFor(() =>
      expect(screen.getByText(/409: tailored resume is associated with a different job/)).toBeInTheDocument(),
    );
  });

  it("disables create until a job is chosen", async () => {
    setupLoad();
    render(<AssistedApply onNavigate={vi.fn()} />);
    await waitFor(() => screen.getByTestId("apply-picker"));
    expect((screen.getByTestId("apply-create") as HTMLButtonElement).disabled).toBe(true);
  });
});
