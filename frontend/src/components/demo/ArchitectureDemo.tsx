"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  Shield,
  Lock,
  Cpu,
  FileText,
  CheckCircle2,
  AlertTriangle,
  GitBranch,
  Fingerprint,
  Layers,
  Play,
  Pause,
  RotateCcw,
  SkipForward,
  Maximize2,
  Minimize2,
  Share2,
  Radio,
  FileCode,
  Film,
  Presentation,
  AlignLeft,
  Eye,
  EyeOff,
  Volume2,
  VolumeX,
  Subtitles,
} from "lucide-react";

export interface NarrationSegment {
  sceneId: number;
  startSec: number;
  endSec: number;
  text: string;
}

export const VOICE_OVER_SCRIPT: NarrationSegment[] = [
  {
    sceneId: 1,
    startSec: 0,
    endSec: 5,
    text: "KaryaSetu AI starts with one trusted source of information.",
  },
  {
    sceneId: 2,
    startSec: 5,
    endSec: 10,
    text: "The source is validated, secured, classified, and governed by policy.",
  },
  {
    sceneId: 3,
    startSec: 10,
    endSec: 15,
    text: "Policy determines whether processing uses cloud, local, or offline AI.",
  },
  {
    sceneId: 4,
    startSec: 15,
    endSec: 21,
    text: "Relevant evidence is retrieved to ground the transformation in trusted source information.",
  },
  {
    sceneId: 5,
    startSec: 21,
    endSec: 27,
    text: "That trusted context is transformed into multiple audience-specific outputs.",
  },
  {
    sceneId: 6,
    startSec: 27,
    endSec: 33,
    text: "Each output is verified and passes the required approval and dissemination controls.",
  },
  {
    sceneId: 7,
    startSec: 33,
    endSec: 38,
    text: "Provenance, SHA-256 integrity, and Ed25519 signatures make the artifacts verifiable.",
  },
  {
    sceneId: 8,
    startSec: 38,
    endSec: 40,
    text: "One trusted source. Many verified, controlled artifacts.",
  },
];

export interface StepExplanation {
  stepTitle: string;
  whatIsHappening: string;
}

export const STEP_EXPLANATIONS: Record<number, StepExplanation> = {
  1: {
    stepTitle: "Source Ingestion & Integrity Anchoring",
    whatIsHappening: "The authoritative document (PDF/DOCX) is ingested into the isolated perimeter and anchored with a SHA-256 cryptographic digest.",
  },
  2: {
    stepTitle: "Perimeter Defense & Data Classification",
    whatIsHappening: "The source is securely ingested, identity verified, sanitized against prompt injection, and classified into governance tiers.",
  },
  3: {
    stepTitle: "Policy-Controlled Routing (Air-Gapped AI)",
    whatIsHappening: "Zero-trust policy engine evaluates classification: sensitive content hard-blocks external cloud egress, enforcing local air-gapped LLM routing.",
  },
  4: {
    stepTitle: "Evidence Retrieval & RAG Grounding",
    whatIsHappening: "Content is split into verifiable chunks with citation vectors, eliminating hallucinations and ensuring 100% evidence-backed lineage.",
  },
  5: {
    stepTitle: "Simultaneous Multi-Format Synthesis",
    whatIsHappening: "One trusted source context is simultaneously transformed into 7 distinct deliverables: summaries, advisories, slides, social threads, and video packages.",
  },
  6: {
    stepTitle: "Release Verification & Human Sign-Off",
    whatIsHappening: "Every generated output passes multi-stage fact verification, human operator approval, and strict destination dissemination governance before release.",
  },
  7: {
    stepTitle: "Cryptographic Sealing & Signatures",
    whatIsHappening: "Outputs are sealed with tamper-evident SHA-256 integrity digests, signed with Ed25519 digital keys, and linked to provenance records.",
  },
  8: {
    stepTitle: "Governed KaryaSetu AI Platform",
    whatIsHappening: "Complete high-assurance lifecycle: transforming single source intelligence into multiple verified, audit-ready institutional deliverables.",
  },
};

export interface SceneConfig {
  id: number;
  label: string;
  tag: string;
  startSec: number;
  endSec: number;
  title: string;
  subtitle: string;
}

export const SCENES: SceneConfig[] = [
  {
    id: 1,
    label: "Source",
    tag: "01 / 08 · SOURCE ANCHORING",
    startSec: 0,
    endSec: 5,
    title: "ONE TRUSTED SOURCE",
    subtitle: "Ingesting authoritative document into the secure boundary",
  },
  {
    id: 2,
    label: "Ingestion",
    tag: "02 / 08 · PERIMETER & POSTURE",
    startSec: 5,
    endSec: 10,
    title: "SECURE INGESTION",
    subtitle: "Identity verification, threat defense & deterministic classification",
  },
  {
    id: 3,
    label: "Policy Route",
    tag: "03 / 08 · ROUTING GOVERNANCE",
    startSec: 10,
    endSec: 15,
    title: "POLICY-CONTROLLED AI",
    subtitle: "Deterministic model routing governed strictly by data classification",
  },
  {
    id: 4,
    label: "Evidence",
    tag: "04 / 08 · EVIDENCE CHAIN",
    startSec: 15,
    endSec: 21,
    title: "EVIDENCE-GROUNDED TRANSFORMATION",
    subtitle: "RAG chunking, citation binding & hallucination mitigation",
  },
  {
    id: 5,
    label: "Multi-Output",
    tag: "05 / 08 · MULTI-CHANNEL SYNTHESIS",
    startSec: 21,
    endSec: 27,
    title: "ONE SOURCE → MANY OUTPUTS",
    subtitle: "Simultaneous multi-format transformation from a single intelligence context",
  },
  {
    id: 6,
    label: "Governance",
    tag: "06 / 08 · RELEASE GATING",
    startSec: 27,
    endSec: 33,
    title: "VERIFY BEFORE RELEASE",
    subtitle: "Multi-stage verification, human sign-off & dissemination control",
  },
  {
    id: 7,
    label: "Integrity",
    tag: "07 / 08 · CRYPTOGRAPHIC SEAL",
    startSec: 33,
    endSec: 38,
    title: "CRYPTOGRAPHICALLY VERIFIABLE ARTIFACT",
    subtitle: "Authoritative SHA-256 integrity digest & Ed25519 digital signature",
  },
  {
    id: 8,
    label: "Platform",
    tag: "08 / 08 · COMPLETE PLATFORM",
    startSec: 38,
    endSec: 40,
    title: "KARYASETU AI",
    subtitle: "Gen AI Platform for Automated Content Transformation",
  },
];

const TOTAL_DURATION_SEC = 40;

export interface ArchitectureDemoProps {
  autoPlay?: boolean;
  reducedMotion?: boolean;
  mode?: "full" | "landing";
  speed?: number;
}

export function ArchitectureDemo({
  autoPlay = true,
  reducedMotion = false,
  mode = "full",
  speed,
}: ArchitectureDemoProps = {}) {
  const isLanding = mode === "landing";
  const defaultSpeed = isLanding ? (speed ?? 2) : (speed ?? 1);

  const [currentMs, setCurrentMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(autoPlay && !reducedMotion);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(defaultSpeed);
  const [isCleanMode, setIsCleanMode] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isReducedMotion, setIsReducedMotion] = useState(reducedMotion);
  const [isHovered, setIsHovered] = useState(false);

  // Audio Voice-Over & Caption states
  const [isMuted, setIsMuted] = useState(true);
  const [showCaptions, setShowCaptions] = useState(true);
  const [audioAvailable, setAudioAvailable] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const lastTimeRef = useRef<number | null>(null);
  const animFrameRef = useRef<number | null>(null);

  // Check prefers-reduced-motion
  useEffect(() => {
    if (reducedMotion) {
      setIsReducedMotion(true);
      setIsPlaying(false);
      return;
    }
    if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
      try {
        const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
        if (mq && mq.matches) {
          setIsReducedMotion(true);
          setIsPlaying(false);
        }
      } catch {
        // Graceful fallback in environments without matchMedia support
      }
    }
  }, [reducedMotion]);

  const isPlayingRef = useRef(isPlaying);
  isPlayingRef.current = isPlaying;
  const isMutedRef = useRef(isMuted);
  isMutedRef.current = isMuted;
  const currentMsRef = useRef(currentMs);
  currentMsRef.current = currentMs;

  // Safe audio pause helper for environments (like jsdom) without full MediaElement support
  const safePause = (audio?: HTMLAudioElement | null) => {
    if (!audio) return;
    try {
      audio.pause();
    } catch {
      // Gracefully swallow unhandled pause calls in test environments
    }
  };

  // Audio element initialization with fallback handling
  useEffect(() => {
    if (typeof window === "undefined" || typeof Audio === "undefined") return;

    try {
      const audio = new Audio("/audio/karyasetu-architecture-voiceover.mp3");
      audio.preload = "auto";
      audio.muted = isMutedRef.current;

      const handleCanPlay = () => setAudioAvailable(true);
      const handleError = () => {
        // Missing audio asset or load error is caught gracefully without interrupting animation
        setAudioAvailable(false);
      };
      const handleEnded = () => {
        if (isLanding) {
          audio.currentTime = 0;
          if (isPlayingRef.current && !isMutedRef.current) {
            audio.play().catch(() => {});
          }
        }
      };

      audio.addEventListener("canplay", handleCanPlay);
      audio.addEventListener("error", handleError);
      audio.addEventListener("ended", handleEnded);
      audioRef.current = audio;

      return () => {
        audio.removeEventListener("canplay", handleCanPlay);
        audio.removeEventListener("error", handleError);
        audio.removeEventListener("ended", handleEnded);
        safePause(audio);
        audio.src = "";
        audioRef.current = null;
      };
    } catch {
      setAudioAvailable(false);
    }
  }, [isLanding]);

  // IntersectionObserver: Pause when out of view, play when visible
  useEffect(() => {
    if (!isLanding || !containerRef.current) return;
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          if (!isReducedMotion) {
            setIsPlaying(true);
          }
        } else {
          setIsPlaying(false);
        }
      },
      { threshold: 0.35 }
    );

    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [isLanding, isReducedMotion]);

  // Audio play/pause state synchronization
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying && !isMuted && audioAvailable) {
      const targetSec = currentMsRef.current / 1000;
      if (Math.abs(audio.currentTime - targetSec) > 0.4) {
        audio.currentTime = targetSec;
      }
      audio.playbackRate = 1.0;
      audio.muted = false;
      const playPromise = audio.play();
      if (playPromise !== undefined) {
        playPromise.catch(() => {});
      }
    } else {
      safePause(audio);
    }
  }, [isPlaying, isMuted, audioAvailable]);

  // Efficient, lag-free playback loop (ticks 20 times/sec, ~0% CPU usage)
  useEffect(() => {
    if (!isPlaying) return;

    const interval = setInterval(() => {
      setCurrentMs((prev) => {
        const next = prev + 50 * playbackSpeed;
        if (next >= TOTAL_DURATION_SEC * 1000) {
          if (isLanding) {
            if (audioRef.current) {
              audioRef.current.currentTime = 0;
            }
            return 0; // Seamless continuous loop in landing mode
          }
          setIsPlaying(false);
          safePause(audioRef.current);
          return TOTAL_DURATION_SEC * 1000;
        }
        return next;
      });
    }, 50);

    return () => clearInterval(interval);
  }, [isPlaying, playbackSpeed, isLanding]);

  const currentSec = currentMs / 1000;

  // Determine current active scene
  const activeScene =
    SCENES.find((s) => currentSec >= s.startSec && currentSec < s.endSec) ||
    SCENES[SCENES.length - 1];

  // Determine active narration script segment for closed captions
  const activeCaption =
    VOICE_OVER_SCRIPT.find((s) => currentSec >= s.startSec && currentSec < s.endSec) ||
    VOICE_OVER_SCRIPT[VOICE_OVER_SCRIPT.length - 1];

  const handlePlayPause = useCallback(() => {
    if (currentSec >= TOTAL_DURATION_SEC) {
      setCurrentMs(0);
      if (audioRef.current) {
        audioRef.current.currentTime = 0;
      }
      setIsPlaying(true);
    } else {
      setIsPlaying((prev) => !prev);
    }
  }, [currentSec]);

  const handleRestart = useCallback(() => {
    setCurrentMs(0);
    if (audioRef.current) {
      audioRef.current.currentTime = 0;
      if (!isMuted && audioAvailable) {
        audioRef.current.play().catch(() => {});
      }
    }
    setIsPlaying(true);
  }, [isMuted, audioAvailable]);

  const handleJumpToScene = useCallback((scene: SceneConfig) => {
    setCurrentMs(scene.startSec * 1000);
    if (audioRef.current) {
      audioRef.current.currentTime = scene.startSec;
    }
  }, []);

  const handleNextScene = useCallback(() => {
    const nextIndex = SCENES.findIndex((s) => s.id === activeScene.id) + 1;
    if (nextIndex < SCENES.length) {
      setCurrentMs(SCENES[nextIndex].startSec * 1000);
      if (audioRef.current) {
        audioRef.current.currentTime = SCENES[nextIndex].startSec;
      }
    }
  }, [activeScene.id]);

  const handleSkip = useCallback(() => {
    const finalScene = SCENES[SCENES.length - 1];
    setCurrentMs(finalScene.startSec * 1000);
    if (audioRef.current) {
      audioRef.current.currentTime = finalScene.startSec;
      safePause(audioRef.current);
    }
    setIsPlaying(false);
  }, []);

  const toggleMute = useCallback(() => {
    setIsMuted((prev) => {
      const next = !prev;
      if (!next) {
        // Unmuting: ensure animation runs at 1x normal speed so narration is clear and intelligible
        setPlaybackSpeed(1);
        if (audioRef.current) {
          audioRef.current.currentTime = currentMs / 1000;
          audioRef.current.playbackRate = 1.0;
          audioRef.current.muted = false;
          if (isPlaying && audioAvailable) {
            audioRef.current.play().catch(() => {});
          }
        }
      } else {
        if (audioRef.current) {
          safePause(audioRef.current);
          audioRef.current.muted = true;
        }
      }
      return next;
    });
  }, [currentMs, isPlaying, audioAvailable]);

  const handleSpeedChange = useCallback((speedOption: number) => {
    setPlaybackSpeed(speedOption);
    if (speedOption !== 1 && !isMuted) {
      setIsMuted(true);
      if (audioRef.current) {
        safePause(audioRef.current);
        audioRef.current.muted = true;
      }
    }
  }, [isMuted]);

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen?.().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.().catch(() => {});
      setIsFullscreen(false);
    }
  };

  // Keyboard navigation for desktop full mode only
  useEffect(() => {
    if (isLanding) return; // No global keyboard listeners in landing mode

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.code === "Space") {
        e.preventDefault();
        handlePlayPause();
      } else if (e.code === "KeyR") {
        e.preventDefault();
        handleRestart();
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        handleNextScene();
      } else if (e.code === "KeyM") {
        e.preventDefault();
        toggleMute();
      } else if (e.code === "KeyC") {
        e.preventDefault();
        setShowCaptions((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isLanding, handlePlayPause, handleRestart, handleNextScene, toggleMute]);

  return (
    <div
      ref={containerRef}
      onClick={() => {
        if (isLanding) handlePlayPause();
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`relative flex flex-col w-full bg-[#07090E] text-slate-100 font-sans select-none overflow-hidden transition-all ${
        isLanding
          ? "aspect-square md:aspect-auto h-full cursor-pointer group"
          : isFullscreen
          ? "h-screen rounded-none border-none"
          : "min-h-[640px] md:min-h-[700px] rounded-2xl border border-slate-800/80 shadow-2xl"
      }`}
      role="region"
      aria-label="KaryaSetu AI Architecture Demo Animation"
    >
      {/* Background Matrix & Lighting Grid */}
      <div className="absolute inset-0 bg-[radial-gradient(#1E293B_1px,transparent_1px)] [background-size:24px_24px] opacity-25 pointer-events-none" />
      <div className="absolute -top-32 -left-32 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute -bottom-32 -right-32 w-96 h-96 bg-emerald-600/10 rounded-full blur-3xl pointer-events-none" />

      {/* Top Minimal Watermark & Voice Controls in Landing Mode */}
      {isLanding && (
        <div className="absolute top-2.5 left-3 right-3 z-20 flex items-center justify-between text-xs pointer-events-none">
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
            <span className="font-mono text-[10px] uppercase text-slate-300 font-semibold tracking-wider">
              {!isMuted ? "Zero-Trust Architecture · 1X Voice-Over" : `Zero-Trust Architecture · ${playbackSpeed}X Speed`}
            </span>
          </div>
          <div className="flex items-center gap-1.5 pointer-events-auto">
            {/* Speed pills in landing mode */}
            <div className="flex items-center rounded bg-slate-900/90 border border-slate-700/80 p-0.5 text-[10px] font-mono">
              {[1, 1.5, 2].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSpeedChange(s);
                  }}
                  className={`px-1.5 py-0.5 rounded transition-colors ${
                    playbackSpeed === s ? "bg-blue-600 text-white font-bold" : "text-slate-400 hover:text-slate-200"
                  }`}
                  title={`Speed ${s}x`}
                  aria-label={`Set speed to ${s}x`}
                >
                  {s}x
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                toggleMute();
              }}
              className={`p-1 rounded backdrop-blur-md transition-colors border ${
                !isMuted
                  ? "bg-emerald-600 text-white border-emerald-500"
                  : "bg-slate-900/80 text-slate-400 border-slate-700/80 hover:text-white"
              }`}
              title={!isMuted ? "Mute voice-over" : "Unmute voice-over"}
              aria-label={!isMuted ? "Mute voice-over" : "Unmute voice-over"}
            >
              {!isMuted ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setShowCaptions((prev) => !prev);
              }}
              className={`px-1.5 py-0.5 rounded backdrop-blur-md transition-colors border font-mono text-[10px] ${
                showCaptions
                  ? "bg-indigo-600/70 text-white border-indigo-500"
                  : "bg-slate-900/80 text-slate-400 border-slate-700/80 hover:text-white"
              }`}
              title="Toggle closed captions"
              aria-label="Toggle closed captions"
            >
              CC
            </button>
            <span className="font-mono text-[10px] text-slate-400 ml-1">
              {activeScene.id} / {SCENES.length}
            </span>
          </div>
        </div>
      )}


      {/* Bottom Thin Loop Progress Bar in Landing Mode */}
      {isLanding && (
        <div className="absolute bottom-0 left-0 right-0 h-1 bg-slate-900 z-20 overflow-hidden pointer-events-none">
          <div
            className="h-full bg-gradient-to-r from-blue-500 via-indigo-500 to-emerald-400 transition-all duration-75 ease-linear"
            style={{ width: `${(currentSec / TOTAL_DURATION_SEC) * 100}%` }}
          />
        </div>
      )}

      {/* Top Header Bar in Full Mode */}
      {!isLanding && (
        <div className="relative z-10 flex items-center justify-between px-6 py-4 border-b border-slate-800/60 bg-[#07090E]/90 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-600 text-white font-bold shadow-lg shadow-blue-500/20">
              K
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold tracking-tight text-white">KaryaSetu AI</span>
                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Core Engine
                </span>
              </div>
              <p className="text-[11px] text-slate-400 font-mono">Architecture & Execution Sequence</p>
            </div>
          </div>

          {/* Scene Badge & Clock */}
          <div className="flex items-center gap-4 font-mono">
            <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-900/80 border border-slate-800 text-xs text-slate-300">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>{activeScene.tag}</span>
            </div>
            <div className="text-xs font-semibold px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-200">
              {formatTime(currentSec)} / {formatTime(TOTAL_DURATION_SEC)}
            </div>
          </div>
        </div>
      )}

      {/* Main Animated Stage Area */}
      <div
        className={`relative flex-1 flex flex-col justify-center items-center overflow-hidden ${
          isLanding ? "p-3 sm:p-4 pt-7" : "p-6 md:p-10"
        }`}
      >
        {/* Stage Header Text */}
        <div
          className={`text-center transition-all duration-300 ${
            isLanding ? "mb-2 max-w-lg" : "mb-8 max-w-2xl"
          }`}
        >
          <span
            className={`inline-block font-mono font-medium tracking-widest text-emerald-400 uppercase ${
              isLanding ? "text-[9px] mb-0.5" : "text-xs mb-2"
            }`}
          >
            {activeScene.tag}
          </span>
          {isLanding ? (
            <div
              role="presentation"
              className="font-extrabold tracking-tight text-white text-base sm:text-lg mb-0.5"
            >
              {activeScene.title}
            </div>
          ) : (
            <h1 className="font-extrabold tracking-tight text-white text-2xl md:text-4xl mb-2">
              {activeScene.title}
            </h1>
          )}
          <p
            className={`text-slate-400 max-w-md mx-auto leading-relaxed ${
              isLanding ? "text-[10px] line-clamp-1" : "text-xs md:text-sm"
            }`}
          >
            {activeScene.subtitle}
          </p>
        </div>

        {/* Dynamic Scene Renderer */}
        <div className="w-full max-w-4xl flex-1 flex items-center justify-center">
          {activeScene.id === 1 && <Scene1Source currentSec={currentSec} isCompact={isLanding} />}
          {activeScene.id === 2 && <Scene2Ingestion currentSec={currentSec} isCompact={isLanding} />}
          {activeScene.id === 3 && <Scene3PolicyRouting currentSec={currentSec} isCompact={isLanding} />}
          {activeScene.id === 4 && <Scene4EvidenceTransformation currentSec={currentSec} isCompact={isLanding} />}
          {activeScene.id === 5 && <Scene5Outputs currentSec={currentSec} isCompact={isLanding} />}
          {activeScene.id === 6 && <Scene6Governance currentSec={currentSec} isCompact={isLanding} />}
          {activeScene.id === 7 && <Scene7CryptographicSeal currentSec={currentSec} isCompact={isLanding} />}
          {activeScene.id === 8 && <Scene8PlatformHero currentSec={currentSec} isCompact={isLanding} />}
        </div>

        {/* Synchronized Closed Captions & Self-Explanatory Step Subtitles */}
        {showCaptions && (
          <div
            className={`w-full max-w-3xl px-3 sm:px-4 mx-auto rounded-xl bg-slate-950/95 border border-slate-700/80 backdrop-blur-md text-center transition-all duration-300 shadow-2xl z-20 ${
              isLanding ? "mt-1 mb-1 py-1.5 sm:py-2" : "mt-6 py-3 px-5"
            }`}
          >
            <div className="flex flex-wrap items-center justify-center gap-1.5 sm:gap-2 mb-0.5">
              <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono text-[9px] uppercase tracking-wider font-semibold">
                CC · VOICE-OVER
              </span>
              <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-mono text-[9px] uppercase tracking-wider font-bold">
                STEP {activeCaption.sceneId}/8 · {STEP_EXPLANATIONS[activeCaption.sceneId]?.stepTitle || activeScene.title}
              </span>
              <span className="text-[10px] font-mono text-slate-400">
                {formatTime(activeCaption.startSec)}–{formatTime(activeCaption.endSec)}
              </span>
              {!isMuted && (
                <span className="inline-flex items-center gap-1 text-[9px] font-mono text-emerald-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  1× NARRATION
                </span>
              )}
            </div>

            {/* Main Script Text */}
            <p
              className={`text-white font-semibold leading-snug ${
                isLanding ? "text-xs sm:text-[13px]" : "text-xs md:text-sm"
              }`}
            >
              &ldquo;{activeCaption.text}&rdquo;
            </p>

            {/* Self-Explanatory Step Details */}
            <p
              className={`text-slate-300 font-normal leading-relaxed mt-0.5 ${
                isLanding ? "text-[10px] sm:text-[11px] line-clamp-2" : "text-xs"
              }`}
            >
              <span className="text-emerald-400 font-semibold font-mono mr-1">▶ WHAT IS HAPPENING:</span>
              {STEP_EXPLANATIONS[activeCaption.sceneId]?.whatIsHappening}
            </p>
          </div>
        )}
      </div>

      {/* Persistent Scene Scrubber & Timeline Tabs (Full Mode Only) */}
      {!isLanding && !isCleanMode && (
        <div className="relative z-10 border-t border-slate-800/80 bg-[#090C12]/95 backdrop-blur-md px-6 py-4 space-y-3">
          {/* Progress bar */}
          <div className="relative w-full h-1.5 bg-slate-800 rounded-full overflow-hidden cursor-pointer">
            <div
              className="h-full bg-gradient-to-r from-blue-500 via-indigo-500 to-emerald-400 transition-all duration-100 ease-linear rounded-full"
              style={{ width: `${(currentSec / TOTAL_DURATION_SEC) * 100}%` }}
            />
          </div>

          {/* Controls & Scene Jumper */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handlePlayPause}
                className="flex items-center justify-center w-8 h-8 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                title={isPlaying ? "Pause (Space)" : "Play (Space)"}
                aria-label={isPlaying ? "Pause animation" : "Play animation"}
              >
                {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 translate-x-0.5" />}
              </button>

              <button
                type="button"
                onClick={handleRestart}
                className="flex items-center justify-center w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
                title="Restart (R)"
                aria-label="Restart animation"
              >
                <RotateCcw className="w-4 h-4" />
              </button>

              <button
                type="button"
                onClick={handleNextScene}
                className="flex items-center justify-center w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
                title="Next Scene (→)"
                aria-label="Next scene"
              >
                <SkipForward className="w-4 h-4" />
              </button>

              <button
                type="button"
                onClick={handleSkip}
                className="px-2.5 py-1 text-xs rounded bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 font-mono transition-colors"
                title="Skip to final overview"
                aria-label="Skip animation"
              >
                Skip
              </button>

              {/* Mute / Unmute Voice-Over */}
              <button
                type="button"
                onClick={toggleMute}
                className={`flex items-center justify-center w-8 h-8 rounded-lg transition-colors border ${
                  !isMuted
                    ? "bg-emerald-600 text-white border-emerald-500 hover:bg-emerald-500 shadow-sm"
                    : "bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700"
                }`}
                title={!isMuted ? "Mute voice-over (M)" : "Unmute voice-over (M)"}
                aria-label={!isMuted ? "Mute voice-over" : "Unmute voice-over"}
                aria-pressed={!isMuted}
              >
                {!isMuted ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
              </button>

              {/* Closed Captions Toggle */}
              <button
                type="button"
                onClick={() => setShowCaptions((prev) => !prev)}
                className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded border font-mono transition-colors ${
                  showCaptions
                    ? "bg-indigo-600/30 text-indigo-300 border-indigo-500/50"
                    : "bg-slate-900 hover:bg-slate-800 text-slate-400 border-slate-800"
                }`}
                title="Toggle closed captions (C)"
                aria-label="Toggle closed captions"
                aria-pressed={showCaptions}
              >
                <Subtitles className="w-3.5 h-3.5" />
                <span>CC</span>
              </button>

              {/* Speed toggle */}
              <div className="flex items-center rounded-lg bg-slate-900 border border-slate-800 p-0.5 text-[11px] font-mono">
                {[1, 1.5, 2].map((speedOption) => (
                  <button
                    key={speedOption}
                    type="button"
                    onClick={() => handleSpeedChange(speedOption)}
                    className={`px-2 py-0.5 rounded ${
                      playbackSpeed === speedOption ? "bg-blue-600 text-white" : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {speedOption}x
                  </button>
                ))}
              </div>
            </div>

            {/* Scene Selectors */}
            <div className="hidden lg:flex items-center gap-1">
              {SCENES.map((scene) => (
                <button
                  key={scene.id}
                  type="button"
                  onClick={() => handleJumpToScene(scene)}
                  className={`px-2 py-1 rounded text-[10px] font-mono uppercase transition-all ${
                    activeScene.id === scene.id
                      ? "bg-blue-500/20 text-blue-400 border border-blue-500/40"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/60"
                  }`}
                >
                  {scene.id}. {scene.label}
                </button>
              ))}
            </div>

            {/* Clean recording mode & fullscreen */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsCleanMode(true)}
                className="flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 font-mono transition-colors"
                title="Hide controls for clean screen recording"
              >
                <EyeOff className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Record Mode</span>
              </button>

              <button
                type="button"
                onClick={toggleFullscreen}
                className="flex items-center justify-center w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
                title="Toggle fullscreen"
                aria-label="Toggle fullscreen"
              >
                {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Floating Restore Controls Button if in Clean Mode */}
      {!isLanding && isCleanMode && (
        <button
          type="button"
          onClick={() => setIsCleanMode(false)}
          className="absolute bottom-4 right-4 z-50 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-xs text-slate-300 border border-slate-700 font-mono backdrop-blur-md transition-all shadow-lg"
        >
          <Eye className="w-3.5 h-3.5" />
          <span>Show Controls</span>
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Scene 1: ONE TRUSTED SOURCE
// ---------------------------------------------------------------------------

function Scene1Source({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  const progress = Math.min(1, Math.max(0, (currentSec - 0) / 5));

  return (
    <div
      className={`flex items-center justify-center w-full animate-fade-in ${
        isCompact ? "flex-col gap-3 max-w-sm" : "flex-col md:flex-row gap-8 max-w-2xl"
      }`}
    >
      {/* Source Document Card */}
      <div
        className={`relative flex flex-col rounded-xl border border-blue-500/40 bg-slate-900/80 shadow-2xl shadow-blue-500/10 transition-transform duration-500 ${
          isCompact ? "p-3.5 w-60" : "p-6 w-72"
        }`}
        style={{
          transform: `scale(${0.95 + progress * 0.05}) translateY(${Math.sin(progress * Math.PI) * -4}px)`,
        }}
      >
        <div className="flex items-center justify-between mb-3">
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[10px] font-mono">
            <FileText className="w-3.5 h-3.5" />
            PDF / DOCX / TXT
          </span>
          <span className="text-[10px] font-mono text-emerald-400 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
            READY
          </span>
        </div>

        <div className="space-y-1.5 mb-3">
          <div className="h-2.5 w-3/4 bg-slate-700 rounded" />
          <div className="h-2 w-full bg-slate-800 rounded" />
          <div className="h-2 w-5/6 bg-slate-800 rounded" />
        </div>

        <div className="pt-2.5 border-t border-slate-800/80 text-[10px] font-mono text-slate-400 space-y-1">
          <div className="flex justify-between">
            <span>Authoritative SHA-256</span>
            <span className="text-slate-300">9f86d081...</span>
          </div>
          <div className="flex justify-between">
            <span>Content Boundary</span>
            <span className="text-emerald-400">Delimited</span>
          </div>
        </div>
      </div>

      {/* Ingress Stream Animation */}
      <div className="flex flex-col items-center gap-1.5">
        <div className="flex items-center gap-1.5 text-[11px] font-mono text-blue-400">
          <Radio className="w-3.5 h-3.5 animate-pulse" />
          <span>Ingress Stream</span>
        </div>
        <div className="w-28 h-1 bg-slate-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-300"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
        <span className="text-[9px] font-mono text-slate-500">Zero Network Leakage</span>
      </div>

      {/* Target Ingestion Gateway (only in full mode) */}
      {!isCompact && (
        <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/40 text-center w-64">
          <Shield className="w-8 h-8 text-blue-400 mx-auto mb-2" />
          <h3 className="text-sm font-semibold text-white">Ingestion Perimeter</h3>
          <p className="text-[11px] text-slate-400 mt-1">Direct memory parsing & hash anchoring</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene 2: SECURE INGESTION
// ---------------------------------------------------------------------------

function Scene2Ingestion({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  const step = Math.min(3, Math.floor((currentSec - 5) / 1.5));

  const tiers = [
    { name: "PUBLIC", desc: "Open distribution", active: step >= 0, color: "text-slate-300 border-slate-700" },
    { name: "INTERNAL", desc: "Workgroup access", active: step >= 1, color: "text-blue-400 border-blue-500/40" },
    { name: "CONFIDENTIAL", desc: "Controlled release", active: step >= 2, color: "text-amber-400 border-amber-500/40" },
    { name: "RESTRICTED", desc: "Air-gapped local only", active: step >= 3, color: "text-rose-400 border-rose-500/50 bg-rose-500/10" },
  ];

  return (
    <div className={`w-full animate-fade-in ${isCompact ? "max-w-md space-y-2.5" : "max-w-3xl space-y-6"}`}>
      {/* 3 Pipeline Defensive Steps */}
      <div className="grid grid-cols-3 gap-2">
        <div className="p-2.5 sm:p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 text-center">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 mx-auto mb-1" />
          <div className="text-[11px] font-semibold text-white">1. Identity</div>
          <div className="text-[9px] font-mono text-emerald-400 mt-0.5">Authenticated Owner</div>
        </div>
        <div className="p-2.5 sm:p-3 rounded-xl border border-blue-500/30 bg-blue-500/5 text-center">
          <Shield className="w-4 h-4 text-blue-400 mx-auto mb-1" />
          <div className="text-[11px] font-semibold text-white">2. Input Defense</div>
          <div className="text-[9px] font-mono text-blue-400 mt-0.5">Stream Sanitation</div>
        </div>
        <div className="p-2.5 sm:p-3 rounded-xl border border-purple-500/30 bg-purple-500/5 text-center">
          <Layers className="w-4 h-4 text-purple-400 mx-auto mb-1" />
          <div className="text-[11px] font-semibold text-white">3. Classification</div>
          <div className="text-[9px] font-mono text-purple-400 mt-0.5">Deterministic Tiers</div>
        </div>
      </div>

      {/* Sensitivity Tiers Readout */}
      <div className={`rounded-xl border border-slate-800 bg-slate-900/60 ${isCompact ? "p-2.5 space-y-1.5" : "p-5 space-y-3"}`}>
        <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
          <span>CLASSIFICATION MATRIX (CONCEPTUAL GOVERNANCE)</span>
          <span className="text-rose-400 font-semibold">SELECTED: RESTRICTED</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
          {tiers.map((t) => (
            <div
              key={t.name}
              className={`p-2 rounded-lg border text-center transition-all ${
                t.active ? t.color : "border-slate-800/40 text-slate-600 opacity-40"
              }`}
            >
              <div className="text-[10px] font-bold font-mono">{t.name}</div>
              <div className="text-[8px] text-slate-400 mt-0.5 line-clamp-1">{t.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene 3: POLICY-CONTROLLED AI
// ---------------------------------------------------------------------------

function Scene3PolicyRouting({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  const isEnforced = currentSec >= 12;

  return (
    <div className={`w-full animate-fade-in ${isCompact ? "max-w-md space-y-2" : "max-w-3xl space-y-6"}`}>
      <div className="text-center font-mono text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 py-1.5 px-2 rounded-lg line-clamp-1">
        POLICY DECISION: SENSITIVE DATA FORBIDS EXTERNAL CLOUD EGRESS
      </div>

      <div className={`grid gap-2 ${isCompact ? "grid-cols-3" : "grid-cols-1 md:grid-cols-3 gap-4"}`}>
        {/* Route 1: Cloud */}
        <div className="p-2.5 sm:p-3 rounded-xl border border-rose-500/40 bg-rose-500/5 relative overflow-hidden">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-mono text-rose-400 font-bold">ROUTE: CLOUD</span>
            <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 text-[8px] font-mono font-bold">
              FORBIDDEN
            </span>
          </div>
          <p className="text-[10px] text-slate-300 mb-1">External APIs</p>
          <div className="text-[9px] text-rose-400 font-semibold font-mono">Egress Blocked</div>
        </div>

        {/* Route 2: Local */}
        <div className="p-2.5 sm:p-3 rounded-xl border border-slate-700 bg-slate-900/60">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-mono text-blue-400 font-bold">ROUTE: LOCAL</span>
            <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 text-[8px] font-mono">
              PERMITTED
            </span>
          </div>
          <p className="text-[10px] text-slate-300 mb-1">Local Daemon</p>
          <div className="text-[9px] text-slate-400 font-mono">Standby Node</div>
        </div>

        {/* Route 3: Air-Gapped / Offline */}
        <div
          className={`p-2.5 sm:p-3 rounded-xl border transition-all duration-500 ${
            isEnforced
              ? "border-emerald-500 bg-emerald-500/10 shadow-lg shadow-emerald-500/10"
              : "border-slate-800 bg-slate-900/40"
          }`}
        >
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-mono text-emerald-400 font-bold">ROUTE: AIR-GAPPED / OFFLINE</span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[8px] font-mono font-bold">
              ENFORCED
            </span>
          </div>
          <p className="text-[10px] text-slate-300 mb-1">Isolated Weights</p>
          <div className="text-[9px] text-emerald-400 font-mono">Zero Egress</div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene 4: EVIDENCE-GROUNDED TRANSFORMATION
// ---------------------------------------------------------------------------

function Scene4EvidenceTransformation({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  const nodes = [
    { label: "Chunk #1", type: "Section 4.2", hash: "sha256-a1b2..." },
    { label: "Chunk #2", type: "Statistical Table", hash: "sha256-c3d4..." },
    { label: "Chunk #3", type: "Regulatory Directive", hash: "sha256-e5f6..." },
  ];

  return (
    <div
      className={`w-full flex items-center justify-between animate-fade-in ${
        isCompact ? "flex-col sm:flex-row gap-2.5 max-w-md" : "flex-col md:flex-row gap-6 max-w-3xl"
      }`}
    >
      {/* Evidence Nodes */}
      <div className="flex-1 space-y-1.5 w-full">
        <span className="text-[10px] font-mono text-slate-400">AUTHORITATIVE SOURCE CHUNKS</span>
        {nodes.map((n, i) => (
          <div
            key={n.label}
            className="p-2 rounded-lg border border-slate-800 bg-slate-900/80 flex items-center justify-between text-[10px] font-mono"
            style={{ animationDelay: `${i * 150}ms` }}
          >
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
              <span className="text-white font-semibold">{n.label}</span>
              <span className="text-slate-400">({n.type})</span>
            </div>
            <span className="text-[9px] text-slate-500">{n.hash}</span>
          </div>
        ))}
      </div>

      {/* Flow connector (full mode only) */}
      {!isCompact && (
        <div className="flex flex-col items-center text-slate-500 font-mono text-[10px] gap-1">
          <GitBranch className="w-6 h-6 text-indigo-400 animate-pulse" />
          <span>RAG Grounding</span>
        </div>
      )}

      {/* Synthesis Engine Box */}
      <div className="flex-1 p-3 sm:p-4 rounded-xl border border-indigo-500/40 bg-indigo-500/5 text-center w-full">
        <Cpu className="w-6 h-6 text-indigo-400 mx-auto mb-1" />
        <h3 className="text-xs font-semibold text-white">Transformation Engine</h3>
        <p className="text-[10px] text-indigo-300 mt-0.5">Evidence-bound context assembly</p>
        <div className="mt-2 inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-[9px] font-mono text-emerald-400">
          <CheckCircle2 className="w-2.5 h-2.5" />
          <span>No Hallucination · Grounded Lineage</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene 5: ONE SOURCE → MANY OUTPUTS (All 7 real outputs)
// ---------------------------------------------------------------------------

export const OUTPUT_FORMATS = [
  { name: "Executive Summary", format: "Markdown", badge: "Text", color: "text-purple-400 border-purple-500/30", icon: AlignLeft },
  { name: "Advisory Circular", format: "Directives", badge: "Gov", color: "text-amber-400 border-amber-500/30", icon: FileText },
  { name: "Presentation", format: "16:9 PPTX", badge: "Slides", color: "text-teal-400 border-teal-500/30", icon: Presentation },
  { name: "LinkedIn Post", format: "Professional", badge: "Social", color: "text-sky-400 border-sky-500/30", icon: Share2 },
  { name: "X Thread", format: "Micro-Broadcast", badge: "Social", color: "text-slate-300 border-slate-700", icon: Radio },
  { name: "Infographic", format: "Visual Data", badge: "Visual", color: "text-orange-400 border-orange-500/30", icon: FileCode },
  { name: "Video Package", format: "Storyboard + SRT", badge: "Storyboard", color: "text-pink-400 border-pink-500/30", icon: Film },
];

function Scene5Outputs({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  return (
    <div className={`w-full animate-fade-in ${isCompact ? "max-w-md space-y-2" : "max-w-4xl space-y-4"}`}>
      <div className={`grid gap-1.5 ${isCompact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3"}`}>
        {OUTPUT_FORMATS.map((out) => {
          const Icon = out.icon;
          return (
            <div
              key={out.name}
              className={`p-2 rounded-lg border bg-slate-900/70 hover:bg-slate-900 transition-all flex flex-col justify-between ${out.color}`}
            >
              <div className="flex items-center justify-between mb-1">
                <Icon className="w-3.5 h-3.5" />
                <span className="text-[9px] font-mono text-slate-400">{out.format}</span>
              </div>
              <div>
                <div className="text-[11px] font-semibold text-white leading-tight">{out.name}</div>
                <div className="text-[9px] font-mono text-emerald-400 mt-0.5 flex items-center gap-1">
                  <CheckCircle2 className="w-2 h-2" />
                  Grounded
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="p-1.5 rounded-lg border border-slate-800 bg-slate-900/40 text-center text-[10px] text-slate-400 font-mono">
        Video is structured as a native VideoPackage (storyboard panels, audio cues, timed subtitle cues).
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene 6: VERIFY BEFORE RELEASE (Governance & Dissemination)
// ---------------------------------------------------------------------------

function Scene6Governance({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  return (
    <div className={`w-full animate-fade-in ${isCompact ? "max-w-md space-y-2" : "max-w-3xl space-y-5"}`}>
      <div className={`grid gap-2 ${isCompact ? "grid-cols-3" : "grid-cols-1 md:grid-cols-3 gap-4"}`}>
        {/* Gate 1: Verification */}
        <div className="p-2.5 sm:p-3 rounded-xl border border-blue-500/40 bg-slate-900/60 space-y-1">
          <div className="text-[9px] font-mono text-blue-400 uppercase">GATE 1 · VERIFICATION</div>
          <div className="text-xs font-semibold text-white">Fact Check</div>
          <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[9px] font-mono">
            <CheckCircle2 className="w-2.5 h-2.5" />
            STATUS: SUPPORTED
          </div>
        </div>

        {/* Gate 2: Approval */}
        <div className="p-2.5 sm:p-3 rounded-xl border border-amber-500/40 bg-slate-900/60 space-y-1">
          <div className="text-[9px] font-mono text-amber-400 uppercase">GATE 2 · HUMAN APPROVAL</div>
          <div className="text-xs font-semibold text-white">Controlled Release</div>
          <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 text-[9px] font-mono">
            <AlertTriangle className="w-2.5 h-2.5" />
            OPERATOR APPROVAL
          </div>
        </div>

        {/* Gate 3: Dissemination */}
        <div className="p-2.5 sm:p-3 rounded-xl border border-rose-500/40 bg-slate-900/60 space-y-1">
          <div className="text-[9px] font-mono text-rose-400 uppercase">GATE 3 · DISSEMINATION</div>
          <div className="text-xs font-semibold text-white">Destination Policy</div>
          <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 text-[9px] font-mono font-bold">
            <Lock className="w-2.5 h-2.5" />
            PUBLIC: BLOCKED
          </div>
        </div>
      </div>

      <div className="p-2 rounded-lg border border-rose-500/30 bg-rose-500/5 text-center font-mono text-[10px] text-rose-300">
        POLICY SUPREMACY ENFORCED: Approval cannot override a dissemination policy hard-block.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene 7: CRYPTOGRAPHICALLY VERIFIABLE ARTIFACT
// ---------------------------------------------------------------------------

function Scene7CryptographicSeal({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  return (
    <div
      className={`w-full rounded-xl border border-emerald-500/40 bg-slate-900/80 shadow-2xl animate-fade-in ${
        isCompact ? "max-w-md p-3.5 space-y-2" : "max-w-2xl p-6 space-y-4"
      }`}
    >
      <div className="flex items-center justify-between border-b border-slate-800 pb-2">
        <div className="flex items-center gap-1.5">
          <Fingerprint className="w-4 h-4 text-emerald-400" />
          <span className="text-xs font-bold text-white font-mono">CRYPTOGRAPHIC INTEGRITY RECORD</span>
        </div>
        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[9px] font-mono font-bold">
          STATUS: VERIFIED
        </span>
      </div>

      <div className="space-y-1 text-[11px] font-mono text-slate-300">
        <div className="flex justify-between p-1.5 rounded bg-slate-800/40">
          <span className="text-slate-400">Algorithm</span>
          <span className="text-white font-bold">SHA-256</span>
        </div>
        <div className="flex justify-between p-1.5 rounded bg-slate-800/40">
          <span className="text-slate-400">Artifact Digest</span>
          <span className="text-emerald-400">9f86d081884c7d65...</span>
        </div>
        <div className="flex justify-between p-1.5 rounded bg-slate-800/40">
          <span className="text-slate-400">Digital Signature</span>
          <span className="text-blue-400">Ed25519 (Key ID: gov-sign-2026-prod)</span>
        </div>
        <div className="flex justify-between p-1.5 rounded bg-slate-800/40">
          <span className="text-slate-400">Provenance Manifest</span>
          <span className="text-purple-400">Bound to Source Hash & Approval ID</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scene 8: KARYASETU AI HERO OUTRO
// ---------------------------------------------------------------------------

function Scene8PlatformHero({ currentSec, isCompact }: { currentSec: number; isCompact?: boolean }) {
  return (
    <div
      className={`w-full text-center animate-fade-in ${
        isCompact ? "max-w-sm space-y-2.5" : "max-w-xl space-y-6"
      }`}
    >
      <div
        className={`flex items-center justify-center rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-emerald-500 text-white font-black mx-auto shadow-2xl shadow-blue-500/30 ${
          isCompact ? "w-10 h-10 text-lg" : "w-16 h-16 text-2xl"
        }`}
      >
        K
      </div>

      <div className="space-y-0.5">
        <h2
          className={`font-extrabold text-white tracking-tight ${
            isCompact ? "text-xl sm:text-2xl" : "text-3xl md:text-5xl"
          }`}
        >
          KaryaSetu AI
        </h2>
        <p className="text-[10px] font-mono text-blue-400">
          Gen AI Platform for Automated Content Transformation
        </p>
      </div>

      <div className="p-2.5 rounded-xl border border-slate-800 bg-slate-900/60 max-w-sm mx-auto">
        <p className="text-xs font-medium text-slate-200">
          &ldquo;One Trusted Source → Many Verified, Controlled Artifacts&rdquo;
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-1.5 text-[9px] font-mono text-slate-400">
        <span className="px-2 py-0.5 rounded-full bg-slate-900 border border-slate-800">
          Zero-Trust Ingestion
        </span>
        <span className="px-2 py-0.5 rounded-full bg-slate-900 border border-slate-800">
          Air-Gapped AI
        </span>
        <span className="px-2 py-0.5 rounded-full bg-slate-900 border border-slate-800">
          Cryptographic Integrity
        </span>
      </div>
    </div>
  );
}
