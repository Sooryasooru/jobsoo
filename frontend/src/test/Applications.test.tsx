import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Applications from "../views/Applications";
import { applicationsApi, ApiError } from "../api";
import type { ApplicationRow, ApplicationsBoard, AvailabilityInfo } from "../types";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
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

const api = vi.mocked(applicationsApi);

function row(overrides: Partial<ApplicationRow> = {}): ApplicationRow {
  return {
    id: "app-1",
    job_id: "job-1",
    status: "prepared",
    notes: null,
    submitted_at: null,
    tailored_resume_id: null,
    created_at: "2026-10-20T08:00:00Z",
    updated_at: "2026-10-22T08:00:00Z",
    job_title: "Backend Engineer",
    job_company: "ACME",
    job_canonical_url: "https://jobs.example.com/100",
    job_is_active: true,
    job_is_expired: false,
    job_source: "adzuna",
    allowed_transitions: ["submitted", "withdrawn", "closed"],
    ...overrides,
  };
}

function board(items: ApplicationRow[], counts: Record<string, number> = {}): ApplicationsBoard {
  return { items, counts };
}

const AVAILABILITY_UNKNOWN: AvailabilityInfo = {
  outcome: "unknown",
  reason: "no fresh source verification available",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Applications board", () => {
  it("renders applications and reports API failures clearly", async () => {
    api.board.mockImplementationOnce(() => Promise.reject(new ApiError(500, "boom")));
    render(<Applications />);
    await waitFor(() => expect(screen.getByText(/500: boom/)).toBeInTheDocument());
  });

  it("shows the empty state when there are no applications", async () => {
    api.board.mockResolvedValueOnce(board([]));
    render(<Applications />);
    await waitFor(() => expect(screen.getByText(/No applications yet/)).toBeInTheDocument());
  });

  it("filters by status and search text", async () => {
    api.board.mockResolvedValue(
      board([
        row({ id: "a1", status: "prepared", job_company: "ACME" }),
        row({ id: "a2", status: "submitted", job_company: "Beta", submitted_at: "2026-10-21T00:00:00Z" }),
      ]),
    );
    const user = userEvent.setup();
    render(<Applications />);
    await screen.findByText("ACME — Backend Engineer");
    await screen.findByText(/Beta — Backend Engineer/);

    await user.selectOptions(screen.getByLabelText("Filter by status"), "submitted");
    expect(screen.getByText(/Beta — Backend Engineer/)).toBeInTheDocument();
    expect(screen.queryByText(/ACME — Backend Engineer/)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Filter by status"), "all");
    await user.type(screen.getByLabelText("Search applications"), "acme");
    expect(screen.getByText(/ACME — Backend Engineer/)).toBeInTheDocument();
    expect(screen.queryByText(/Beta — Backend Engineer/)).not.toBeInTheDocument();
  });

  it("'I applied' calls confirmSubmit and updates the row status", async () => {
    const before = row({ id: "a1", status: "prepared" });
    api.board.mockResolvedValueOnce(board([before]));
    api.confirmSubmit.mockResolvedValueOnce(
      row({
        id: "a1",
        status: "submitted",
        submitted_at: "2026-10-23T09:00:00Z",
        allowed_transitions: ["interviewing", "assessment", "rejected", "offer", "withdrawn", "closed"],
      }),
    );
    api.events.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<Applications />);
    const button = await screen.findByTestId("confirm-submit-a1");
    await user.click(button);
    await waitFor(() => expect(api.confirmSubmit).toHaveBeenCalledWith("a1"));
    await waitFor(() => expect(screen.getByTestId("app-board-controls")).toBeInTheDocument());
    expect(await screen.findByText("Submitted 2026-10-23")).toBeInTheDocument();
  });

  it("shows invalid-transition errors from the backend", async () => {
    api.board.mockResolvedValueOnce(
      board([row({ id: "a1", status: "queued", allowed_transitions: ["prepared", "withdrawn", "closed"] })]),
    );
    api.setStatus.mockRejectedValueOnce(new ApiError(409, "invalid transition: queued -> closed"));
    const user = userEvent.setup();
    render(<Applications />);
    await screen.findByText("ACME — Backend Engineer");
    await user.selectOptions(screen.getByLabelText("Change status"), "closed");
    await waitFor(() => expect(screen.getByText(/409: invalid transition/)).toBeInTheDocument());
  });

  it("displays availability warnings after a recheck", async () => {
    api.board.mockResolvedValueOnce(board([row({ id: "a1" })]));
    api.availability.mockResolvedValueOnce(AVAILABILITY_UNKNOWN);
    const user = userEvent.setup();
    render(<Applications />);
    await screen.findByText("ACME — Backend Engineer");
    await user.click(screen.getByText("Check availability"));
    await waitFor(() =>
      expect(screen.getByTestId("availability-a1")).toHaveTextContent(/cannot be verified/i),
    );
    expect(screen.queryByText("Listing open at the source")).not.toBeInTheDocument();
  });
});
