---
name: TransformIQ Operational Engine
colors:
  surface: '#0f131c'
  surface-dim: '#0f131c'
  surface-bright: '#353942'
  surface-container-lowest: '#0a0e16'
  surface-container-low: '#181c24'
  surface-container: '#1c2028'
  surface-container-high: '#262a33'
  surface-container-highest: '#31353e'
  on-surface: '#dfe2ee'
  on-surface-variant: '#c3c6d7'
  inverse-surface: '#dfe2ee'
  inverse-on-surface: '#2c3039'
  outline: '#8d90a0'
  outline-variant: '#434655'
  surface-tint: '#b4c5ff'
  primary: '#b4c5ff'
  on-primary: '#002a78'
  primary-container: '#2563eb'
  on-primary-container: '#eeefff'
  inverse-primary: '#0053db'
  secondary: '#4cd7f6'
  on-secondary: '#003640'
  secondary-container: '#03b5d3'
  on-secondary-container: '#00424e'
  tertiary: '#c0c1ff'
  on-tertiary: '#1000a9'
  tertiary-container: '#585be6'
  on-tertiary-container: '#f1eeff'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#dbe1ff'
  primary-fixed-dim: '#b4c5ff'
  on-primary-fixed: '#00174b'
  on-primary-fixed-variant: '#003ea8'
  secondary-fixed: '#acedff'
  secondary-fixed-dim: '#4cd7f6'
  on-secondary-fixed: '#001f26'
  on-secondary-fixed-variant: '#004e5c'
  tertiary-fixed: '#e1e0ff'
  tertiary-fixed-dim: '#c0c1ff'
  on-tertiary-fixed: '#07006c'
  on-tertiary-fixed-variant: '#2f2ebe'
  background: '#0f131c'
  on-background: '#dfe2ee'
  surface-variant: '#31353e'
typography:
  headline-xl:
    fontFamily: Geist
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 44px
    letterSpacing: -0.025em
  headline-xl-mobile:
    fontFamily: Geist
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Geist
    fontSize: 20px
    fontWeight: '500'
    lineHeight: 28px
    letterSpacing: -0.015em
  headline-sm:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
    letterSpacing: -0.005em
  body-md:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: 0em
  body-sm:
    fontFamily: Geist
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
    letterSpacing: 0em
  label-mono-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-mono-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.04em
  caption:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
    letterSpacing: 0.01em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  grid-margin-desktop: 1.5rem
  grid-margin-tablet: 1rem
  grid-margin-mobile: 0.75rem
  panel-gap: 1rem
  card-padding-dense: 0.75rem
  card-padding-regular: 1.25rem
  inspector-width: 24rem
  rail-width-collapsed: 4rem
  rail-width-expanded: 16rem
---

## Brand & Style

This design system targets high-consequence intelligence analysts, cybersecurity operators, defense specialists, and enterprise executives. The aesthetic rejects playful, consumer-facing generative chat tropes in favor of an authoritative, precision-engineered analytical workspace. 

The design combines the ergonomics of high-density intelligence interfaces with the meticulous boundary control of modern developer software. Operational trust is communicated through structural clarity, deterministic hierarchy, and forensic attention to metadata provenance. Visual density is balanced: high data-to-pixel ratios prevail within workspace panels, framed by disciplined structural margins. The resulting interface feels resolute, uncompromisingly secure, and mission-critical.

## Colors

The palette employs a deep obsidian and slate foundation paired with analytical spectral accents that represent cryptographic verification, automated pipeline states, and data provenance.

- **Foundational Surfaces**: Dark mode establishes the operational default. The base canvas anchors at Obsidian `#0B0F17`, stepping to Slate Surface `#111827` for panels and cards, and Elevation Layer `#1E293B` for hover actions and active viewports. For light-mode enterprise operations, the foundation flips to `#FFFFFF` on `#F8FAFC` slate canvas with crisp `#E2E8F0` structural delimiters.
- **Primary Operational Cobalt (`#2563EB` / `#3B82F6`)**: Applied to primary operational triggers, deterministic workflows, active transformations, and focused system anchors.
- **Provenance Cyan (`#06B6D4`)**: Reserved exclusively for machine provenance, lineage traces, cryptographic chain anchors, and vector integrity metrics.
- **Intelligence Indigo (`#6366F1`)**: Designates retrieval-augmented generation (RAG) grounding, context-window embeddings, and source-grounded outputs.
- **Operational Status Indicators**:
  - `Verified / Cleared`: Emerald `#10B981` (Surface tint: `rgba(16, 185, 129, 0.12)`)
  - `Processing / Staged Review`: Amber `#F59E0B` (Surface tint: `rgba(245, 158, 11, 0.12)`)
  - `Critical Breach / Discrepancy`: Crimson `#EF4444` (Surface tint: `rgba(239, 68, 68, 0.12)`)

## Typography

Typographic hierarchy enforces rapid scanning and auditability across dense telemetry screens. 

- **Primary Interface Font**: Geist provides neutral geometric clarity with mechanical precision. Its tight apertures and tall x-height preserve legibility in data grids, transformation streams, and multi-pane analysis docks.
- **Monospaced Data Font**: JetBrains Mono serves technical parameters, source hash verification, cryptographic tokens, status badges, timestamps, and model attribution metrics.
- **Numerical Formatting**: Tabular figures (`tnum`) and zero-slashed alternatives are enforced globally across telemetry dashboards, execution latency monitors, and statistical outputs.

## Layout & Spacing

The layout is built on a 4px base spatial unit organized into an operational multi-column analytical workspace.

- **Structure**: The view uses a persistent 3-column operational layout:
  1. Primary navigation rail (collapsible between `4rem` icon mode and `16rem` expanded hierarchy).
  2. Main transformation canvas (fluid grid utilizing 12 analytical columns with `1rem` gutters).
  3. Contextual inspector dock (`24rem` pinned right utility rail for metadata, source attribution, and security provenance).
- **Responsive Adaptations**:
  - **Desktop (>= 1280px)**: 3-pane concurrent operation. Inspector and navigation remain docked.
  - **Tablet (768px – 1279px)**: Inspector transitions to an overlay drawer; data transformation stage prioritizes tabular output and split-pane diff comparisons.
  - **Mobile (< 768px)**: Canvas condenses to single-column stacking; telemetry cards reduce interior padding to `0.75rem` (`card-padding-dense`); tabular data collapses to structured key-value list items.

## Elevation & Depth

Visual hierarchy uses low-contrast architectural borders and deliberate tonal planes rather than diffuse shadows.

- **Borders over Shadows**: Boundaries are defined by razor-sharp `1px` structural borders (`rgba(255, 255, 255, 0.08)` in dark mode; `#E2E8F0` in light mode).
- **Tonal Stepping**:
  - `Level 0 (Canvas)`: `#0B0F17` – System base foundation.
  - `Level 1 (Panels & Docks)`: `#111827` – Raised workstation surfaces, workspace containers.
  - `Level 2 (Cards & Modules)`: `#1E293B` – Interactive modules, execution stages, and draggable pipelines.
  - `Level 3 (Overlays & Menus)`: `#1E293B` with border `rgba(59, 130, 246, 0.3)` and an ambient shadow `0 8px 24px rgba(0, 0, 0, 0.45)`.
- **Active Focus & Processing Glow**: Critical processing elements do not cast standard blur shadows. Instead, they project a focused, directional keyline glow: `0 0 0 1px #2563EB, 0 0 12px rgba(37, 99, 235, 0.2)`.

## Shapes

The design system uses soft, calibrated geometry (`roundedness: 1`). Controls maintain a sharp, engineered profile:

- Base actionable inputs, buttons, and badges leverage `0.25rem` (4px).
- Main analytical modules, cards, and canvas panels employ `0.5rem` (`rounded-lg` / 8px).
- Modals, inspector frames, and floating command palettes resolve at `0.75rem` (`rounded-xl` / 12px).
- Rounded pill shapes (`rounded-full`) are strictly forbidden except for live status pulse dots (3px radius).

## Components

### Buttons & Trigger Controls
- **Primary Operational Button**: High-emphasis Cobalt `#2563EB` background, `#FFFFFF` text, `0.25rem` border-radius, `1px` border of `rgba(255, 255, 255, 0.1)`. Active states compress subtly (`scale(0.98)`).
- **Secondary / Ghost**: Deep Obsidian `#111827` surface with a `1px` border in `#1E293B`. Hover shifts to `#1E293B` with a `#3B82F6` border accent.
- **Destructive / Abort**: `#111827` surface with `1px` border in `rgba(239, 68, 68, 0.4)`. Text `#EF4444`.

### Trust Badges & State Chips
- **Micro Badges**: JetBrains Mono 11px uppercase labels, `0.25rem` radius, `2px 6px` interior padding.
- **State Signatures**:
  - `VERIFIED`: Emerald `#10B981` text, dark emerald field `rgba(16, 185, 129, 0.1)`, `1px` stroke `rgba(16, 185, 129, 0.25)`. Includes an inline verified shield vector.
  - `GROUNDED RAG`: Indigo `#6366F1` text, `rgba(99, 102, 241, 0.1)` field, `1px` stroke `rgba(99, 102, 241, 0.3)`.
  - `PROVENANCE TRACED`: Cyan `#06B6D4` text, `rgba(6, 182, 212, 0.08)` field, `1px` stroke `rgba(6, 182, 212, 0.3)`.

### Input Fields & Command Buffers
- **Structure**: Surface `#111827`, inset border `1px` in `#1E293B`, Geist 14px typography. Height standard: `36px` for operational density.
- **Focus Mode**: Zero ring glow; transitions strictly to `1px` solid Cobalt `#2563EB` with monospaced parameter shortcuts surfaced right-aligned.

### Intelligence Cards & Canvas Tiles
- Structured headers containing an upper metadata rail (timestamp, clearance, model provenance) separated by a clean `1px` horizontal separator (`#1E293B`).
- Content area features selectable text, syntax highlighting for structured schema outputs (JSON, STIX/TAXII, Markdown), and a locked lower telemetry footer.

### Artifact Output Viewers (Inspection Docks)
- Split-screen comparison utilities featuring live transformation diffs.
- Source chunk highlights correlating downstream generated text to source intelligence documents using provenance cyan `#06B6D4` bracket markers on hover.