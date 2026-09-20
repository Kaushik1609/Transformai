"use client";

import React, { useState } from "react";
import {
  ShieldCheck,
  FileCheck,
  Cpu,
  Blocks,
  Fingerprint,
  CheckCircle2,
  Lock,
  Link as LinkIcon,
} from "lucide-react";

interface WorkflowNode {
  id: string;
  name: string;
  subtitle: string;
  badge: string;
  x: number;
  y: number;
  color: string;
  ringColor: string;
  haloColor: string;
  icon: React.ComponentType<{ className?: string }>;
  guarantee: string;
  securityDetail: string;
}

interface WorkflowEdge {
  id: string;
  from: string;
  to: string;
  path: string;
  badge: string;
  lineStyle: "solid" | "dashed" | "dotted";
  color: string;
  particleColor: string;
  speed: number; // in seconds
  pillOffset?: { dx?: number; dy?: number };
}

const NODES: WorkflowNode[] = [
  {
    id: "source",
    name: "Source Ingest",
    subtitle: "SHA-256 Digest",
    badge: "01",
    x: 65,
    y: 70,
    color: "#0284c7",
    ringColor: "#38bdf8",
    haloColor: "rgba(56, 189, 248, 0.18)",
    icon: FileCheck,
    guarantee: "Deterministic SHA-256 hash anchored at upload moment.",
    securityDetail: "Ingests PDF/DOCX · Zero byte tampering allowed",
  },
  {
    id: "security",
    name: "Zero-Trust Gate",
    subtitle: "PII & Malware Shield",
    badge: "02",
    x: 205,
    y: 55,
    color: "#d97706",
    ringColor: "#fbbf24",
    haloColor: "rgba(251, 191, 36, 0.18)",
    icon: ShieldCheck,
    guarantee: "Deterministic PII masking & fail-closed malware filter.",
    securityDetail: "Luhn algorithm + ClamAV + Anti-prompt injection",
  },
  {
    id: "policy",
    name: "Policy Enclave",
    subtitle: "RBAC Clearance",
    badge: "03",
    x: 345,
    y: 55,
    color: "#4f46e5",
    ringColor: "#818cf8",
    haloColor: "rgba(129, 140, 248, 0.18)",
    icon: Cpu,
    guarantee: "LLM may recommend; deterministic policy must decide.",
    securityDetail: "Strict classification: Public · Confidential · Restricted",
  },
  {
    id: "provenance",
    name: "Cryptographic Integrity & Provenance",
    subtitle: "SHA-256 · Ed25519",
    badge: "04",
    x: 475,
    y: 125,
    color: "#059669",
    ringColor: "#34d399",
    haloColor: "rgba(52, 211, 153, 0.18)",
    icon: Blocks,
    guarantee: "Cryptographic audit record & verifiable lineage receipt.",
    securityDetail: "SHA-256 · Ed25519 · Audit Lineage",
  },
  {
    id: "seal",
    name: "Cryptographic Seal",
    subtitle: "Verifiable Dissemination",
    badge: "05",
    x: 235,
    y: 195,
    color: "#7c3aed",
    ringColor: "#a78bfa",
    haloColor: "rgba(167, 139, 250, 0.18)",
    icon: Fingerprint,
    guarantee: "Evidence-grounded output with verifiable provenance watermark.",
    securityDetail: "Signed token + citation graph · Verifiable seal",
  },
];

const EDGES: WorkflowEdge[] = [
  {
    id: "e-source-security",
    from: "source",
    to: "security",
    path: "M 65 70 C 110 50, 155 50, 205 55",
    badge: "SHA-256 Digest",
    lineStyle: "solid",
    color: "#38bdf8",
    particleColor: "#38bdf8",
    speed: 3.2,
    pillOffset: { dx: 135, dy: 43 },
  },
  {
    id: "e-security-policy",
    from: "security",
    to: "policy",
    path: "M 205 55 C 250 45, 300 45, 345 55",
    badge: "Zero-Trust",
    lineStyle: "solid",
    color: "#fbbf24",
    particleColor: "#fbbf24",
    speed: 2.8,
    pillOffset: { dx: 275, dy: 40 },
  },
  {
    id: "e-policy-provenance",
    from: "policy",
    to: "provenance",
    path: "M 345 55 C 410 50, 460 75, 475 125",
    badge: "Integrity Anchor",
    lineStyle: "dashed",
    color: "#34d399",
    particleColor: "#34d399",
    speed: 3.4,
    pillOffset: { dx: 425, dy: 72 },
  },
  {
    id: "e-provenance-seal",
    from: "provenance",
    to: "seal",
    path: "M 475 125 C 455 185, 355 200, 235 195",
    badge: "Integrity Seal",
    lineStyle: "solid",
    color: "#a78bfa",
    particleColor: "#a78bfa",
    speed: 3.6,
    pillOffset: { dx: 360, dy: 188 },
  },
  {
    id: "e-source-seal",
    from: "source",
    to: "seal",
    path: "M 65 70 C 60 155, 140 195, 235 195",
    badge: "Grounding Link",
    lineStyle: "dotted",
    color: "#818cf8",
    particleColor: "#818cf8",
    speed: 4.2,
    pillOffset: { dx: 125, dy: 172 },
  },
];

export function SecurityBlockchainWorkflow() {
  const [selectedNode, setSelectedNode] = useState<WorkflowNode | null>(null);

  const activeInfo = selectedNode ?? NODES[3]; // Default to Cryptographic Integrity & Provenance focus

  return (
    <div className="w-full rounded-xl border border-border bg-card p-4 shadow-sm transition-all">
      {/* Header bar: Live status indicator */}
      <div className="mb-2.5 flex items-center justify-between border-b border-border/60 pb-2">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          <span className="text-[11px] font-semibold tracking-wider uppercase text-muted-foreground">
            Zero-Trust &amp; Cryptographic Lineage Pipeline
          </span>
        </div>
        <div className="flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
          <Lock className="h-3 w-3" />
          <span>SHA-256 · Ed25519</span>
        </div>
      </div>

      {/* SVG Interactive Canvas */}
      <div className="relative w-full overflow-hidden rounded-lg bg-slate-950/40 dark:bg-black/40 border border-slate-800/40">
        <svg
          viewBox="0 0 540 250"
          className="h-auto w-full select-none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            {/* Subtle diffusion filter for the moving particle */}
            <filter id="auth-particle-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="1.2" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            {/* Subtle node shadow */}
            <filter id="auth-node-shadow" x="-30%" y="-30%" width="160%" height="160%">
              <feDropShadow dx="0" dy="1.5" stdDeviation="2" floodOpacity="0.25" />
            </filter>
          </defs>

          {/* Background Grid Accent */}
          <g opacity="0.05">
            <line x1="0" y1="50" x2="540" y2="50" stroke="currentColor" strokeDasharray="3,3" />
            <line x1="0" y1="125" x2="540" y2="125" stroke="currentColor" strokeDasharray="3,3" />
            <line x1="0" y1="195" x2="540" y2="195" stroke="currentColor" strokeDasharray="3,3" />
          </g>

          {/* 1. Connecting Curved Edges */}
          {EDGES.map((edge) => (
            <g key={edge.id} className="cursor-pointer">
              {/* Background trace for crisp connection */}
              <path
                d={edge.path}
                fill="none"
                stroke={edge.color}
                strokeWidth={1.5}
                strokeOpacity={0.4}
                strokeDasharray={
                  edge.lineStyle === "dashed"
                    ? "6,4"
                    : edge.lineStyle === "dotted"
                    ? "2.5,4"
                    : undefined
                }
              />

              {/* Pill badge on path */}
              {edge.pillOffset && (
                <g
                  transform={`translate(${edge.pillOffset.dx}, ${edge.pillOffset.dy})`}
                  className="pointer-events-none"
                >
                  <rect
                    x="-34"
                    y="-8"
                    width="68"
                    height="16"
                    rx="4"
                    className="fill-slate-900/95 stroke-slate-700/80 dark:fill-black/95 dark:stroke-slate-700"
                    strokeWidth="0.8"
                  />
                  <text
                    x="0"
                    y="3"
                    textAnchor="middle"
                    className="fill-slate-200 text-[8.5px] font-medium tracking-tight"
                  >
                    {edge.badge}
                  </text>
                </g>
              )}

              {/* 2. Traveling Small Ball / Dot Animation */}
              <path id={`auth-path-${edge.id}`} d={edge.path} fill="none" stroke="transparent" />
              <circle r="3" fill={edge.particleColor} filter="url(#auth-particle-glow)">
                <animateMotion
                  dur={`${edge.speed}s`}
                  repeatCount="indefinite"
                  rotate="auto"
                >
                  <mpath href={`#auth-path-${edge.id}`} />
                </animateMotion>
              </circle>
            </g>
          ))}

          {/* 3. Pipeline Nodes */}
          {NODES.map((node) => {
            const isSelected = selectedNode?.id === node.id;
            const Icon = node.icon;

            return (
              <g
                key={node.id}
                transform={`translate(${node.x}, ${node.y})`}
                onClick={() => setSelectedNode(node)}
                className="cursor-pointer transition-transform duration-200 hover:scale-105"
                role="button"
                tabIndex={0}
                aria-label={node.name}
              >
                {/* Node Halo Ring */}
                <circle
                  r={isSelected ? 24 : 20}
                  fill={node.haloColor}
                  className="transition-all duration-300"
                />

                {/* Outer Ring */}
                <circle
                  r="18"
                  fill="#090d16"
                  stroke={node.ringColor}
                  strokeWidth={isSelected ? 2 : 1.2}
                  filter="url(#auth-node-shadow)"
                  className="transition-all duration-200"
                />

                {/* Badge Chip */}
                <circle cx="13" cy="-13" r="6.5" fill={node.color} />
                <text
                  x="13"
                  y="-10.5"
                  textAnchor="middle"
                  className="fill-white text-[7px] font-bold"
                >
                  {node.badge}
                </text>

                {/* Center Icon embedded via foreignObject */}
                <foreignObject x="-10" y="-10" width="20" height="20">
                  <div className="flex h-full w-full items-center justify-center text-white">
                    <Icon className="h-3 w-3" />
                  </div>
                </foreignObject>

                {/* Text Label Below Node */}
                <text
                  x="0"
                  y="28"
                  textAnchor="middle"
                  className="fill-foreground text-[9.5px] font-semibold"
                >
                  {node.name.length > 22 ? `${node.name.slice(0, 20)}…` : node.name}
                </text>
                <text
                  x="0"
                  y="38"
                  textAnchor="middle"
                  className="fill-muted-foreground text-[8px]"
                >
                  {node.subtitle}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Interactive Micro-Detail Pane */}
      <div className="mt-3 rounded-lg border border-border bg-muted/40 p-2.5 transition-all">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-0.5">
            <div className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: activeInfo.color }} />
              <h4 className="text-xs font-semibold text-foreground">
                {activeInfo.name}
              </h4>
              <span className="text-[10px] text-muted-foreground">· {activeInfo.subtitle}</span>
            </div>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {activeInfo.guarantee}
            </p>
          </div>
          <div className="shrink-0 rounded bg-primary/10 px-2 py-0.5 text-[9.5px] font-medium text-primary">
            {activeInfo.badge === "04" ? "Integrity & Provenance" : "Verified"}
          </div>
        </div>

        <div className="mt-2 flex items-center justify-between border-t border-border/50 pt-1.5 text-[10px] text-muted-foreground">
          <span className="font-mono text-[9px] text-muted-foreground/80">
            {activeInfo.securityDetail}
          </span>
          <span className="text-[9px] text-primary">Click node to inspect</span>
        </div>
      </div>

      {/* 3 Core Security & Provenance Badges */}
      <div className="mt-3 grid grid-cols-3 gap-1.5 text-center">
        <div className="rounded border border-border/60 bg-muted/30 p-1.5">
          <div className="flex items-center justify-center gap-1 text-[10.5px] font-semibold text-foreground">
            <ShieldCheck className="h-3 w-3 text-amber-500" />
            <span>Zero-Trust</span>
          </div>
          <p className="text-[9px] text-muted-foreground">Fail-Closed Gate</p>
        </div>

        <div className="rounded border border-border/60 bg-muted/30 p-1.5">
          <div className="flex items-center justify-center gap-1 text-[10.5px] font-semibold text-foreground">
            <Blocks className="h-3 w-3 text-emerald-500" />
            <span>Integrity</span>
          </div>
          <p className="text-[9px] text-muted-foreground">SHA-256 · Ed25519</p>
        </div>

        <div className="rounded border border-border/60 bg-muted/30 p-1.5">
          <div className="flex items-center justify-center gap-1 text-[10.5px] font-semibold text-foreground">
            <Fingerprint className="h-3 w-3 text-purple-500" />
            <span>Provenance</span>
          </div>
          <p className="text-[9px] text-muted-foreground">Auditable Signatures</p>
        </div>
      </div>
    </div>
  );
}
