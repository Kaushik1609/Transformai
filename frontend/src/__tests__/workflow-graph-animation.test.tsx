import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { WorkflowGraphAnimation } from "@/components/demo/WorkflowGraphAnimation";

describe("WorkflowGraphAnimation Component", () => {
  it("renders the workflow graph canvas, header, and core nodes", () => {
    render(<WorkflowGraphAnimation initialTheme="light" />);

    // Header branding
    expect(
      screen.getByText(/KaryaSetu AI · Workflow Stream Animation/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/Live Pulse/i)).toBeInTheDocument();

    // Key pipeline nodes
    expect(screen.getByText(/Authoritative Source Ingestion/i)).toBeInTheDocument();
    expect(screen.getByText(/Perimeter Security & Screening/i)).toBeInTheDocument();
    expect(screen.getByText(/Deterministic Chunker/i)).toBeInTheDocument();
    expect(screen.getByText(/Zero-Trust Policy Engine/i)).toBeInTheDocument();
    expect(screen.getByText(/pgvector Storage/i)).toBeInTheDocument();
    expect(screen.getByText(/Compliant Model Router/i)).toBeInTheDocument();
    expect(screen.getByText(/Semantic RAG Retrieval/i)).toBeInTheDocument();
    expect(screen.getByText(/Content Intelligence Hub/i)).toBeInTheDocument();
    expect(screen.getByText(/Executive Summary & Advisory/i)).toBeInTheDocument();
    expect(screen.getByText(/Presentation Deck/i)).toBeInTheDocument();
    expect(screen.getByText(/Visual Infographic/i)).toBeInTheDocument();
    expect(screen.getByText(/Social Threads/i)).toBeInTheDocument();
    expect(screen.getByText(/Video Package & SRT/i)).toBeInTheDocument();
    expect(screen.getByText(/Verification & Provenance Seal/i)).toBeInTheDocument();
  });

  it("renders moving particle elements along connecting edges", () => {
    const { container } = render(<WorkflowGraphAnimation initialTheme="light" />);

    // Check for animateMotion elements driving the moving ball dots
    const animateMotionElements = container.querySelectorAll("animateMotion");
    expect(animateMotionElements.length).toBeGreaterThan(0);

    // Check for mpath references to edges
    const mpathElements = container.querySelectorAll("mpath");
    expect(mpathElements.length).toBeGreaterThan(0);
  });

  it("toggles play and pause on user action", () => {
    render(<WorkflowGraphAnimation initialTheme="light" />);

    const pauseBtn = screen.getByTitle(/Pause stream animation/i);
    expect(pauseBtn).toBeInTheDocument();

    fireEvent.click(pauseBtn);
    expect(screen.getByTitle(/Resume stream animation/i)).toBeInTheDocument();

    const playBtn = screen.getByTitle(/Resume stream animation/i);
    fireEvent.click(playBtn);
    expect(screen.getByTitle(/Pause stream animation/i)).toBeInTheDocument();
  });

  it("runs at 1x default speed and has no speed selector buttons", () => {
    render(<WorkflowGraphAnimation initialTheme="light" />);

    expect(screen.queryByText("0.5x")).not.toBeInTheDocument();
    expect(screen.queryByText("2x")).not.toBeInTheDocument();
  });

  it("supports filtering by pipeline categories", () => {
    render(<WorkflowGraphAnimation initialTheme="light" />);

    const secFilter = screen.getByText("Security & Policy");
    fireEvent.click(secFilter);
    expect(secFilter).toHaveClass("bg-blue-600");

    const ragFilter = screen.getByText("RAG Grounding");
    fireEvent.click(ragFilter);
    expect(ragFilter).toHaveClass("bg-blue-600");

    const allFilter = screen.getByText("All Flows");
    fireEvent.click(allFilter);
    expect(allFilter).toHaveClass("bg-blue-600");
  });

  it("opens node inspector when a node is clicked", () => {
    render(<WorkflowGraphAnimation initialTheme="light" />);

    // Inspector not open initially
    expect(screen.queryByText(/Architectural Role/i)).not.toBeInTheDocument();

    // Click on Zero-Trust Policy Engine node
    const policyNode = screen.getByText(/Zero-Trust Policy Engine/i);
    fireEvent.click(policyNode);

    // Inspector should now be visible
    expect(screen.getByText(/Architectural Role/i)).toBeInTheDocument();
    expect(screen.getByText(/Zero-Trust Guarantee/i)).toBeInTheDocument();
    expect(screen.getByText(/Data Stream Contract/i)).toBeInTheDocument();
    expect(
      screen.getByText(/CONFIDENTIAL & RESTRICTED content is NEVER sent to commercial cloud LLMs/i)
    ).toBeInTheDocument();

    // Close inspector
    const closeBtn = screen.getByText(/Close Inspector ✕/i);
    fireEvent.click(closeBtn);
    expect(screen.queryByText(/Architectural Role/i)).not.toBeInTheDocument();
  });

  it("renders light and dark appearances without redundant local theme toggle button", () => {
    const { container: lightContainer } = render(<WorkflowGraphAnimation initialTheme="light" />);
    // No redundant local theme button in toolbar
    expect(screen.queryByTitle(/Switch to (Dark|Light)/i)).not.toBeInTheDocument();
    expect(lightContainer.firstChild).toHaveStyle({ backgroundColor: "#ffffff" });

    const { container: darkContainer } = render(<WorkflowGraphAnimation initialTheme="dark" />);
    expect(darkContainer.firstChild).toHaveStyle({ backgroundColor: "#0a0f1d" });
  });

  it("omits the pause/play button in authMode (sign-in animation is always active)", () => {
    render(<WorkflowGraphAnimation authMode={true} />);
    expect(screen.queryByTitle(/Pause stream animation/i)).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Resume stream animation/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Pause")).not.toBeInTheDocument();
    expect(screen.queryByText("Play")).not.toBeInTheDocument();
  });
});
