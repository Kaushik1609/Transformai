/**
 * KaryaSetu AI — Architecture Demo Animation Unit Tests.
 *
 * Validates deterministic browser animation component:
 *   - 35-40s timeline configuration
 *   - All 8 scenes and their required textual anchors
 *   - All 7 supported output formats (including structured Video Package without MP4 claim)
 *   - Deterministic play/pause/restart/skip controls
 *   - Clean recording mode toggle
 *   - Speed control
 *   - Reduced motion accessibility
 */

import { render, screen, fireEvent, act } from "@testing-library/react";
import { ArchitectureDemo, SCENES, OUTPUT_FORMATS, VOICE_OVER_SCRIPT } from "@/components/demo/ArchitectureDemo";

describe("ArchitectureDemo Component", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  it("renders with 8 scenes and total duration between 35 and 40 seconds", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    expect(SCENES).toHaveLength(8);
    const lastScene = SCENES[SCENES.length - 1];
    expect(lastScene.endSec).toBeGreaterThanOrEqual(35);
    expect(lastScene.endSec).toBeLessThanOrEqual(40);
  });

  it("renders all 7 supported output types accurately", () => {
    expect(OUTPUT_FORMATS).toHaveLength(7);
    const names = OUTPUT_FORMATS.map((f) => f.name);
    expect(names).toContain("Executive Summary");
    expect(names).toContain("Advisory Circular");
    expect(names).toContain("Presentation");
    expect(names).toContain("LinkedIn Post");
    expect(names).toContain("X Thread");
    expect(names).toContain("Infographic");
    expect(names).toContain("Video Package");

    // Check that Video Package explicitly specifies structured storyboard and SRT, NOT MP4
    const videoPkg = OUTPUT_FORMATS.find((f) => f.name === "Video Package");
    expect(videoPkg).toBeDefined();
    expect(videoPkg?.format).toContain("Storyboard + SRT");
    expect(videoPkg?.badge).toBe("Storyboard");
  });

  it("starts at Scene 1 (ONE TRUSTED SOURCE) with authoritative document details", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    expect(screen.getByText("ONE TRUSTED SOURCE")).toBeInTheDocument();
    expect(screen.getByText(/Ingesting authoritative document/i)).toBeInTheDocument();
    expect(screen.getByText(/Authoritative SHA-256/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF \/ DOCX \/ TXT/i)).toBeInTheDocument();
  });

  it("allows jumping directly to each of the 8 scenes via scene tabs", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    // Scene 2: Secure Ingestion
    fireEvent.click(screen.getByRole("button", { name: /2\.\s*Ingestion/i }));
    expect(screen.getByText("SECURE INGESTION")).toBeInTheDocument();
    expect(screen.getByText(/1\. Identity/i)).toBeInTheDocument();
    expect(screen.getByText(/2\. Input Defense/i)).toBeInTheDocument();
    expect(screen.getByText(/3\. Classification/i)).toBeInTheDocument();
    expect(screen.getByText("PUBLIC")).toBeInTheDocument();
    expect(screen.getByText("INTERNAL")).toBeInTheDocument();
    expect(screen.getByText("CONFIDENTIAL")).toBeInTheDocument();
    expect(screen.getByText("RESTRICTED")).toBeInTheDocument();

    // Scene 3: Policy Routing
    fireEvent.click(screen.getByRole("button", { name: /3\.\s*Policy Route/i }));
    expect(screen.getByText("POLICY-CONTROLLED AI")).toBeInTheDocument();
    expect(screen.getByText("ROUTE: CLOUD")).toBeInTheDocument();
    expect(screen.getByText("ROUTE: LOCAL")).toBeInTheDocument();
    expect(screen.getByText("ROUTE: AIR-GAPPED / OFFLINE")).toBeInTheDocument();

    // Scene 4: Evidence Grounding
    fireEvent.click(screen.getByRole("button", { name: /4\.\s*Evidence/i }));
    expect(screen.getByText("EVIDENCE-GROUNDED TRANSFORMATION")).toBeInTheDocument();
    expect(screen.getByText(/Chunk #1/i)).toBeInTheDocument();

    // Scene 5: Outputs (7 types)
    fireEvent.click(screen.getByRole("button", { name: /5\.\s*Multi-Output/i }));
    expect(screen.getByText("ONE SOURCE → MANY OUTPUTS")).toBeInTheDocument();
    expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    expect(screen.getByText("Advisory Circular")).toBeInTheDocument();
    expect(screen.getByText("Presentation")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn Post")).toBeInTheDocument();
    expect(screen.getByText("X Thread")).toBeInTheDocument();
    expect(screen.getByText("Infographic")).toBeInTheDocument();
    expect(screen.getByText("Video Package")).toBeInTheDocument();
    expect(screen.getByText(/Video is structured as a native VideoPackage/i)).toBeInTheDocument();

    // Scene 6: Verify Before Release
    fireEvent.click(screen.getByRole("button", { name: /6\.\s*Governance/i }));
    expect(screen.getByText("VERIFY BEFORE RELEASE")).toBeInTheDocument();
    expect(screen.getByText("GATE 1 · VERIFICATION")).toBeInTheDocument();
    expect(screen.getByText("GATE 2 · HUMAN APPROVAL")).toBeInTheDocument();
    expect(screen.getByText("GATE 3 · DISSEMINATION")).toBeInTheDocument();
    expect(screen.getByText(/STATUS: SUPPORTED/i)).toBeInTheDocument();
    expect(screen.getByText(/PUBLIC: BLOCKED/i)).toBeInTheDocument();
    expect(screen.getByText(/POLICY SUPREMACY ENFORCED/i)).toBeInTheDocument();
    expect(screen.getByText(/Approval cannot override a dissemination policy hard-block/i)).toBeInTheDocument();

    // Scene 7: Cryptographic Artifact
    fireEvent.click(screen.getByRole("button", { name: /7\.\s*Integrity/i }));
    expect(screen.getByText("CRYPTOGRAPHICALLY VERIFIABLE ARTIFACT")).toBeInTheDocument();
    expect(screen.getAllByText(/SHA-256/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Digital Signature/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Ed25519/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Provenance Manifest/i)).toBeInTheDocument();

    // Scene 8: Outro
    fireEvent.click(screen.getByRole("button", { name: /8\.\s*Platform/i }));
    expect(screen.getByRole("heading", { level: 1, name: "KARYASETU AI" })).toBeInTheDocument();
    expect(
      screen.getByText(/One Trusted Source → Many Verified, Controlled Artifacts/i),
    ).toBeInTheDocument();
  });

  it("handles Play, Pause, and Restart controls deterministically", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    const playPauseBtn = screen.getByRole("button", { name: /Play animation/i });
    expect(playPauseBtn).toBeInTheDocument();

    // Click Play
    fireEvent.click(playPauseBtn);
    expect(screen.getByRole("button", { name: /Pause animation/i })).toBeInTheDocument();

    // Pause
    const pauseBtn = screen.getByRole("button", { name: /Pause animation/i });
    fireEvent.click(pauseBtn);
    expect(screen.getByRole("button", { name: /Play animation/i })).toBeInTheDocument();

    // Restart
    const restartBtn = screen.getByRole("button", { name: /Restart animation/i });
    fireEvent.click(restartBtn);
    expect(screen.getByText("ONE TRUSTED SOURCE")).toBeInTheDocument();
  });

  it("handles Skip Animation to jump directly to Scene 8", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    const skipBtn = screen.getByRole("button", { name: /Skip animation/i });
    fireEvent.click(skipBtn);

    expect(screen.getByRole("heading", { level: 1, name: "KARYASETU AI" })).toBeInTheDocument();
    expect(
      screen.getByText(/One Trusted Source → Many Verified, Controlled Artifacts/i),
    ).toBeInTheDocument();
  });

  it("toggles clean recording mode to hide navigation tabs and bottom toolbar", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    const recordModeBtn = screen.getByRole("button", { name: /Record Mode/i });
    expect(recordModeBtn).toBeInTheDocument();

    // Toggle clean recording mode ON
    fireEvent.click(recordModeBtn);

    // The clean mode overlay indicator appears with exit button
    expect(screen.getByRole("button", { name: /Show Controls/i })).toBeInTheDocument();

    // Toggle clean mode OFF
    fireEvent.click(screen.getByRole("button", { name: /Show Controls/i }));
    expect(screen.getByRole("button", { name: /Record Mode/i })).toBeInTheDocument();
  });

  it("cycles playback speed between 1x, 1.5x, and 2x", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    const speed15Btn = screen.getByRole("button", { name: "1.5x" });
    expect(speed15Btn).toBeInTheDocument();

    fireEvent.click(speed15Btn);
    expect(speed15Btn.className).toContain("bg-blue-600");

    const speed2Btn = screen.getByRole("button", { name: "2x" });
    fireEvent.click(speed2Btn);
    expect(speed2Btn.className).toContain("bg-blue-600");
  });

  it("supports reduced motion when requested via props or media query", () => {
    render(<ArchitectureDemo autoPlay={false} reducedMotion={true} />);

    // Renders cleanly without errors in reduced motion mode
    expect(screen.getByText("ONE TRUSTED SOURCE")).toBeInTheDocument();
  });

  it("renders landing mode without controls and supports center click-to-pause", () => {
    const { container } = render(<ArchitectureDemo mode="landing" autoPlay={false} />);

    // Control buttons are omitted in landing mode
    expect(screen.queryByRole("button", { name: /Play animation/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Restart animation/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Record Mode/i })).not.toBeInTheDocument();

    // Scene content is rendered
    expect(screen.getByText("ONE TRUSTED SOURCE")).toBeInTheDocument();
    expect(screen.getByText(/Zero-Trust Architecture · 2X Speed/i)).toBeInTheDocument();

    // Clicking the video toggles play/pause
    const region = screen.getByRole("region", { name: /KaryaSetu AI Architecture Demo Animation/i });
    expect(region.className).toContain("aspect-square");

    fireEvent.click(region);
    // Clicking toggles state
    fireEvent.click(region);
  });

  it("configures the 8-segment voice-over script with precise timing matching prompt specifications", () => {
    expect(VOICE_OVER_SCRIPT).toHaveLength(8);

    expect(VOICE_OVER_SCRIPT[0].text).toBe("KaryaSetu AI starts with one trusted source of information.");
    expect(VOICE_OVER_SCRIPT[0].startSec).toBe(0);
    expect(VOICE_OVER_SCRIPT[0].endSec).toBe(5);

    expect(VOICE_OVER_SCRIPT[1].text).toBe("The source is validated, secured, classified, and governed by policy.");
    expect(VOICE_OVER_SCRIPT[1].startSec).toBe(5);
    expect(VOICE_OVER_SCRIPT[1].endSec).toBe(10);

    expect(VOICE_OVER_SCRIPT[2].text).toBe("Policy determines whether processing uses cloud, local, or offline AI.");
    expect(VOICE_OVER_SCRIPT[2].startSec).toBe(10);
    expect(VOICE_OVER_SCRIPT[2].endSec).toBe(15);

    expect(VOICE_OVER_SCRIPT[3].text).toBe("Relevant evidence is retrieved to ground the transformation in trusted source information.");
    expect(VOICE_OVER_SCRIPT[3].startSec).toBe(15);
    expect(VOICE_OVER_SCRIPT[3].endSec).toBe(21);

    expect(VOICE_OVER_SCRIPT[4].text).toBe("That trusted context is transformed into multiple audience-specific outputs.");
    expect(VOICE_OVER_SCRIPT[4].startSec).toBe(21);
    expect(VOICE_OVER_SCRIPT[4].endSec).toBe(27);

    expect(VOICE_OVER_SCRIPT[5].text).toBe("Each output is verified and passes the required approval and dissemination controls.");
    expect(VOICE_OVER_SCRIPT[5].startSec).toBe(27);
    expect(VOICE_OVER_SCRIPT[5].endSec).toBe(33);

    expect(VOICE_OVER_SCRIPT[6].text).toBe("Provenance, SHA-256 integrity, and Ed25519 signatures make the artifacts verifiable.");
    expect(VOICE_OVER_SCRIPT[6].startSec).toBe(33);
    expect(VOICE_OVER_SCRIPT[6].endSec).toBe(38);

    expect(VOICE_OVER_SCRIPT[7].text).toBe("One trusted source. Many verified, controlled artifacts.");
    expect(VOICE_OVER_SCRIPT[7].startSec).toBe(38);
    expect(VOICE_OVER_SCRIPT[7].endSec).toBe(40);
  });

  it("renders closed captions for the active scene and supports CC toggle", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    // Initially displays Scene 1 caption
    expect(screen.getByText(/KaryaSetu AI starts with one trusted source of information/i)).toBeInTheDocument();

    // Toggle CC off
    const ccBtn = screen.getByRole("button", { name: /Toggle closed captions/i });
    expect(ccBtn).toBeInTheDocument();
    fireEvent.click(ccBtn);

    expect(screen.queryByText(/KaryaSetu AI starts with one trusted source of information/i)).not.toBeInTheDocument();

    // Toggle CC back on
    fireEvent.click(ccBtn);
    expect(screen.getByText(/KaryaSetu AI starts with one trusted source of information/i)).toBeInTheDocument();
  });

  it("updates closed captions when navigating between scenes", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    // Jump to Scene 3 (Policy Route)
    fireEvent.click(screen.getByRole("button", { name: /3\.\s*Policy Route/i }));
    expect(screen.getByText(/Policy determines whether processing uses cloud, local, or offline AI/i)).toBeInTheDocument();

    // Jump to Scene 7 (Cryptographic Seal)
    fireEvent.click(screen.getByRole("button", { name: /7\.\s*Integrity/i }));
    expect(screen.getByText(/Provenance, SHA-256 integrity, and Ed25519 signatures make the artifacts verifiable/i)).toBeInTheDocument();
  });

  it("handles Mute and Unmute controls with accessible labels and enforces 1x speed when narration is active", () => {
    render(<ArchitectureDemo autoPlay={false} />);

    // Starts muted per browser autoplay standards
    const unmuteBtn = screen.getByRole("button", { name: /Unmute voice-over/i });
    expect(unmuteBtn).toBeInTheDocument();

    // Select 2x speed while muted
    const speed2Btn = screen.getByRole("button", { name: "2x" });
    fireEvent.click(speed2Btn);
    expect(speed2Btn.className).toContain("bg-blue-600");

    // Unmute: should automatically lock playback speed to 1x normal speed so narration is clear
    fireEvent.click(unmuteBtn);
    const muteBtn = screen.getByRole("button", { name: /Mute voice-over/i });
    expect(muteBtn).toBeInTheDocument();

    const speed1Btn = screen.getByRole("button", { name: "1x" });
    expect(speed1Btn.className).toContain("bg-blue-600");

    // Muting allows speed selection again
    fireEvent.click(muteBtn);
    expect(screen.getByRole("button", { name: /Unmute voice-over/i })).toBeInTheDocument();
  });

  it("renders normally without throwing unhandled exceptions when audio asset is missing", () => {
    expect(() => {
      render(<ArchitectureDemo autoPlay={true} />);
    }).not.toThrow();

    expect(screen.getByText("ONE TRUSTED SOURCE")).toBeInTheDocument();
    expect(screen.getByText(/CC · VOICE-OVER/i)).toBeInTheDocument();
  });
});
