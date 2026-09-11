# TransformIQ — Enterprise Design System & Implementation Specification
**Implementation Target:** Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, Radix UI Primitives, Lucide Icons  
**Platform Classification:** High-Assurance AI Content Transformation Platform (Controlled Sec-RAG v3.4, FIPS 140-3 Enforced)

---

## 1. Product Architectural Foundation & Lexicon

TransformIQ is a controlled enterprise transformation engine for high-assurance intelligence, compliance, and multi-audience dissemination. It is **not** a conversational chatbot or consumer "AI magic" tool.

### Controlled Product Lexicon
| Approved Enterprise Term | Deprecated / Prohibited Term | Context / Rationale |
| :--- | :--- | :--- |
| **Transform / Execute** | Generate magically / Prompt | Deterministic multi-format transformation execution |
| **Source / Ingested Corpus** | Uploaded file / Document attachment | Indexed, chunked, and vector-sharded source asset |
| **Mandate / Guidance Prompt** | Chat prompt / Message | Structured steering vector for synthesis |
| **Communication Deliverables / Artifacts** | AI outputs / Bot responses | Formats (BLUF, Advisory, LinkedIn, Deck, X Thread, Infographic, Video Spec) |
| **Grounding & Provenance** | Fact check / Hallucination score | Cosine similarity token verification against source chunks |
| **Trust Status (Reason-Based)** | Trust percentage (e.g. 98%) | Concrete evidence signals: Claims Grounded, Hash Intact, Zero PII |
| **Enclave / Pod / Project** | Folder / Directory | Isolated security and access control boundary |

---

## 2. Global Layout & Structural Dimensions

```
+----------------------------------------------------------------------------------------------------+
| Top Application Header (h-14 / 56px, border-b, bg-surface-container-low, sticky top-0, z-40)       |
+----------------------+-----------------------------------------------------------------------------+
| Sidebar Navigation   | Main Content Canvas (min-h-[calc(100vh-56px)], bg-surface)                  |
| (w-64 / 256px,       | max-w-7xl (1280px) or max-w-[1600px] fluid for Multi-Column Cockpits        |
|  shrink-0, border-r, | Padding: px-6 py-6 (desktop) / px-4 py-4 (mobile)                           |
|  bg-surface-lowest)  | Gaps: gap-6 (sections), gap-4 (cards), gap-2 (compact controls)             |
+----------------------+-----------------------------------------------------------------------------+
```

### Layout Tokens
* **Top Header Height:** `h-14` (56px)
* **Sidebar Width (Expanded):** `w-64` (256px)
* **Sidebar Width (Collapsed / Tablet):** `w-16` (64px)
* **Mobile Breakpoint:** `< 768px` (Sidebar hides into slide-over drawer; sticky bottom actions or tab bar)
* **Standard Viewport Max-Width:** `max-w-7xl` (1280px) for standard workflows (Create, Settings, Auth)
* **Cockpit / Inspector Max-Width:** `max-w-[1680px]` (fluid 3-column grid for Results & Output Workspace)
* **Z-Index Scale:**
  * Base Content: `z-0`
  * Sticky Headers/Docks: `z-20`
  * Floating Action Bars / Toasts: `z-30`
  * Top Navigation Bar: `z-40`
  * Modals / Sheets / Command Palette (`Cmd+K`): `z-50`

---

## 3. Design Tokens (Tailwind & CSS Custom Properties)

### 3.1 Color Palette & Semantic Color Mapping

```css
:root {
  /* Surface & Base (Dark Enterprise Default) */
  --surface-container-lowest: #0a0e16;
  --surface: #0f131c;
  --surface-dim: #0f131c;
  --surface-container-low: #181c24;
  --surface-container: #1e222b;
  --surface-container-high: #262b35;
  --surface-container-highest: #313642;
  --surface-bright: #353942;

  /* Borders & Dividers */
  --border-subtle: #232834;
  --border-default: #2d3444;
  --border-prominent: #3e475c;

  /* Typography & Foreground */
  --text-primary: #f1f5f9;     /* slate-100 */
  --text-secondary: #94a3b8;   /* slate-400 */
  --text-muted: #64748b;       /* slate-500 */
  --text-inverse: #090d16;

  /* Brand & Interactive (Cobalt Action Vector) */
  --primary-500: #2563eb;      /* blue-600 */
  --primary-400: #3b82f6;      /* blue-500 hover */
  --primary-600: #1d4ed8;      /* active/pressed */
  --primary-900: #1e3a8a;
  --primary-surface: rgba(37, 99, 235, 0.12);

  /* Status Tokens (WCAG Triple-Signal Compliant) */
  --status-success: #10b981;   /* emerald-500 */
  --status-success-bg: rgba(16, 185, 129, 0.12);
  --status-success-border: rgba(16, 185, 129, 0.3);

  --status-warning: #f59e0b;   /* amber-500 */
  --status-warning-bg: rgba(245, 158, 11, 0.12);
  --status-warning-border: rgba(245, 158, 11, 0.3);

  --status-error: #ef4444;     /* red-500 */
  --status-error-bg: rgba(239, 68, 68, 0.12);
  --status-error-border: rgba(239, 68, 68, 0.3);

  --status-info: #0ea5e9;      /* sky-500 */
  --status-info-bg: rgba(14, 165, 233, 0.12);
  --status-info-border: rgba(14, 165, 233, 0.3);

  --status-neutral: #64748b;   /* slate-500 */
  --status-neutral-bg: rgba(100, 116, 139, 0.12);
  --status-neutral-border: rgba(100, 116, 139, 0.25);

  /* Trust States */
  --trust-trusted: #10b981;
  --trust-caution: #f59e0b;
  --trust-unverified: #64748b;
}

/* Light Theme Variables (Subdued, High-Contrast Corporate) */
.light {
  --surface-container-lowest: #ffffff;
  --surface: #f8fafc;
  --surface-dim: #f1f5f9;
  --surface-container-low: #f8fafc;
  --surface-container: #ffffff;
  --surface-container-high: #e2e8f0;
  --surface-container-highest: #cbd5e1;
  --surface-bright: #ffffff;

  --border-subtle: #e2e8f0;
  --border-default: #cbd5e1;
  --border-prominent: #94a3b8;

  --text-primary: #0f172a;     /* slate-900 */
  --text-secondary: #475569;   /* slate-600 */
  --text-muted: #64748b;       /* slate-500 */
  --text-inverse: #f8fafc;

  --primary-500: #1d4ed8;
  --primary-400: #2563eb;
  --primary-600: #1e40af;
  --primary-surface: rgba(29, 78, 216, 0.08);
}
```

### 3.2 Typography System
* **Primary Font:** Geist Sans (`font-sans`), Inter fallback.
* **Monospace Font:** Geist Mono / JetBrains Mono (`font-mono`) — used strictly for SHA-256 hashes, citation identifiers, tokens, chunk indices, and FIPS node IDs.
* **Type Scale & Hierarchy:**
  * **Display Title / Cockpit Header:** `text-2xl` (24px), `font-semibold`, tracking `-0.02em`, `leading-tight`
  * **Section / Card Title:** `text-lg` (18px), `font-medium`, tracking `-0.01em`, `leading-snug`
  * **Subhead / Widget Header:** `text-sm` (14px), `font-semibold`, uppercase tracking `0.05em` (`text-slate-400`)
  * **Body Primary (Deliverable Content):** `text-sm` (14px) / `text-base` (16px), `font-normal`, `leading-relaxed` (1.6)
  * **Data / Metadata / Microcopy:** `text-xs` (12px), `font-medium`, `leading-normal`
  * **Technical Badges / Pills:** `text-[11px]`, `font-semibold`, uppercase tracking `0.06em`

### 3.3 Border Radius, Shadows & Focus Rings
* **Border Radius:**
  * Tags & Code Pills: `rounded` (4px)
  * Buttons, Inputs, Cards: `rounded-md` (6px) or `rounded-lg` (8px)
  * Modals & Enclaves: `rounded-xl` (12px)
  * Avatars & Status Dots: `rounded-full` (9999px)
* **Shadows:**
  * Subdued Depth: `shadow-sm` (`0 1px 2px 0 rgba(0, 0, 0, 0.3)`)
  * Popover / Dropdown / Dock: `shadow-lg shadow-black/40`
  * Modal: `shadow-2xl shadow-black/70`
* **Focus Visible Rings (WCAG 2.1 AAA Compliant):**
  * `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950`

---

## 4. Master Reusable Component Library (shadcn/ui & React Contracts)

### 4.1 Button (`components/ui/button.tsx`)
* **Variants:**
  1. `primary`: `bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-medium shadow-sm transition-all duration-150`
  2. `secondary`: `bg-surface-container border border-border-default hover:bg-surface-container-high text-slate-200`
  3. `destructive`: `bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 active:bg-red-500/30`
  4. `ghost`: `text-slate-400 hover:text-slate-100 hover:bg-white/5`
  5. `outline`: `border border-border-default hover:border-slate-400 text-slate-300`
* **States:** Default, Hover, Pressed (`scale-[0.98]`), Disabled (`opacity-50 cursor-not-allowed pointer-events-none`), Loading (`pointer-events-none` with fixed-width layout preservation and inline SVG spinner).

### 4.2 Badges & Indicator System
* **`TrustBadge` (`components/governance/trust-badge.tsx`)**:
  * `TRUSTED`: `bg-emerald-500/10 text-emerald-400 border border-emerald-500/30` (Icon: `ShieldCheck`)
  * `CAUTION`: `bg-amber-500/10 text-amber-400 border border-amber-500/30` (Icon: `AlertTriangle`)
  * `UNVERIFIED`: `bg-slate-500/10 text-slate-400 border border-slate-500/30` (Icon: `HelpCircle`)
  * *Constraint:* Never shows raw percentages alone; always pairs with substantive count/citations (e.g. `44/44 Grounded`).
* **`SecurityPipelineBadge`**:
  * `Passed` (Emerald), `Warning` (Amber), `Failed` (Red), `Unavailable` (Muted Slate), `Running` (Cobalt pulse).

### 4.3 Form Inputs & Adversarial Validation
* **`Input` / `Textarea`**:
  * Base: `bg-surface-container-low border border-border-default focus:border-blue-500 text-slate-100 placeholder:text-slate-500 rounded-md px-3.5 py-2.5 text-sm`
  * Validation Error State: `border-red-500 ring-1 ring-red-500 text-red-200` with direct proximity error label.
  * Adversarial Protection Badge: Detects prompt injection patterns (`DROP TABLE`, bypass tokens) and displays a deterministic SEC-RAG rejection notice without crashing.
* **`LanguageSelect`**:
  * First-class enterprise selector featuring **English**, **Hindi (हिन्दी)**, and **Marathi (मराठी)** with native font glyph rendering.

### 4.4 Ingestion & Upload Experience (`UploadZone`)
* **Dual-Input Mode Guarantee:**
  * Mode A: *Prompt Only* (Source optional)
  * Mode B: *Source Only* (Prompt optional)
  * Mode C: *Source + Prompt Active* (Both anchored)
  * Bottom Guardrail: `"Provide a source, a prompt, or both."` CTA disables only when both vectors are empty.
* **Dropzone States:**
  * `Idle`: Dashed border `border-border-prominent`, format labels (`PDF, DOCX, TXT, STIX/TAXII JSON max 50MB`).
  * `Dragging`: `border-blue-500 bg-blue-500/10 ring-2 ring-blue-500/30`.
  * `Uploaded Preview Card`: File badge, file size, page count, OCR confidence, and SHA-256 hash.
  * `Malware Quarantine`: Quarantined state with macro detection notice (`Executive_Briefing_Macro.docm`) and incident log trigger.

### 4.5 Output Workspace (One-to-Many Architecture)
* **Left Format Ledger (7 Packages):**
  1. Executive Summary (BLUF format, decision-ready)
  2. Tactical Advisory (MITRE ATT&CK mapped, TLP:AMBER)
  3. LinkedIn Dispatch (Strategic thought leadership)
  4. Presentation Deck (10-slide outline with speaker notes)
  5. X Thread (Sequential multi-post incident narrative)
  6. Infographic Blueprint (SVG/XML vector layout spec)
  7. Video Package (Teleprompter script + B-roll timing cues; clearly labeled non-MP4)
* **Center Document View:**
  * Distraction-free typography, interactive inline citation tags `[Ref: Source p.4 §2]`, actor matrix tables, and immediate copy/export actions.
* **Right Governance Dock:**
  * Real-time grounding score (e.g. `95.4%`), evidence anchor counts, cryptographic SHA-256 digest, and cross-output nuance detection drawer.

---

## 5. Responsive Breakpoint Adaptation Guide

| Screen Element | Desktop (`>= 1024px`) | Tablet (`768px - 1023px`) | Mobile (`< 768px`) |
| :--- | :--- | :--- | :--- |
| **Sidebar** | Fixed `w-64`, persistent | Collapsed `w-16` (icons only) | Hidden in slide-over drawer; accessible via top menu trigger |
| **Header** | Full breadcrumb + search + status pill | Truncated breadcrumb + search modal | Minimal logo + status badge + drawer button |
| **Create Input** | Two-column (Source left, Mandate right) | Stacked vertical cards | Single-column swipeable tabs or stacked accordion |
| **Output Workspace**| 3-Column Cockpit (Ledger / Viewer / Dock) | 2-Column (Ledger & Viewer, Dock as drawer) | 1-Column with horizontal pills for format switching and bottom modal for audit |
| **Data Tables** | Multi-column table with hover rows | Horizontally scrollable container | Stacked card cards with key-value pairs |
| **Action Triggers** | Inline header & card actions | Inline primary actions | Sticky floating bottom bar (`Transform` CTA, min 48px touch height) |

---

## 6. Accessibility & Enterprise Trust Rules

1. **Triple-Signal Rule:** Never communicate status by color alone. Every badge, error, and trust notification must incorporate:
   * **Semantic Icon:** (e.g., `ShieldCheck`, `AlertTriangle`, `XCircle`, `Clock`)
   * **Explicit Text Label:** (`TRUSTED`, `CAUTION`, `UNVERIFIED`)
   * **Contextual Subtitle / Reason:** (`44/44 Claims Grounded`, `1 Nuance Divergence Flagged`)
2. **Zero-Exposure PII Rule:** Detected PII (emails, phone numbers, SSNs) are tracked by category and count (e.g., `14 Emails Masked`) and shown as synthetic tokens (`[REDACTED_EMAIL_01]`). Raw personal records are strictly forbidden from rendering in the client DOM.
3. **Hardware-Backed Authenticity:** Artifact hashes display truncated hex digests (`a81f...92c1`) with one-click copy to clipboard for external verification against FIPS 140-3 enclaves.
4. **Touch Targets:** All buttons, dropdown items, and navigation tabs maintain a minimum interactive hit area of `44px x 44px`.

---

## 7. Developer Implementation Reference: Component Tree

```
src/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   ├── register/page.tsx
│   │   └── otp-verify/page.tsx
│   ├── (dashboard)/
│   │   ├── page.tsx                           # Home / Enterprise Workspace Dashboard
│   │   ├── projects/
│   │   │   ├── page.tsx                       # Projects Directory
│   │   │   └── [projectId]/
│   │   │       ├── sources/page.tsx           # Project Detail & Source Library
│   │   │       └── page.tsx                   # Project Overview
│   │   ├── transform/
│   │   │   ├── new/page.tsx                   # Create Transformation (4-Step Workflow)
│   │   │   └── [transformId]/
│   │   │       ├── page.tsx                   # Results & Verification Cockpit
│   │   │       └── workspace/page.tsx         # Output Workspace & Artifact Inspector
│   │   ├── history/page.tsx                   # Transformation History Ledger
│   │   ├── security/page.tsx                  # Security Activity & Audit Trail
│   │   └── settings/page.tsx                  # Account, Theme & Security Preferences
├── components/
│   ├── ui/                                    # Base shadcn components (button, input, dialog, toast)
│   ├── shell/                                 # AppHeader, AppSidebar, NavItem, Breadcrumbs
│   ├── transformation/                        # SourceUploader, MandateInput, OutputFormatCard, StepBar
│   ├── workspace/                             # OutputLedger, DocumentViewer, DeckPreview, SocialPreview
│   └── governance/                            # TrustBadge, SecurityPipeline, GroundingInspector, HashSeal
└── styles/
    └── globals.css                            # Token variables & Tailwind configuration
```
