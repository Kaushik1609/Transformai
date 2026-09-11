# TransformIQ — Stitch Design Reference

This folder contains the Stitch-generated visual design references for
the TransformIQ frontend.

The Stitch export is a DESIGN REFERENCE and must not directly replace
the existing TransformIQ frontend.

## Functional Authority

The existing TransformIQ repository is authoritative for:

- authentication
- authorization
- backend APIs
- transformation orchestration
- RAG
- LLM providers
- security
- verification
- artifact handling
- output registry
- database contracts
- existing business logic

## Visual Authority

The Stitch references are authoritative for:

- layout
- spacing
- typography
- navigation
- cards
- forms
- visual hierarchy
- responsive design
- interaction presentation
- overall visual direction

## Main Workflow

Dashboard
→ Create Transformation
→ Source and/or Prompt
→ Configuration
→ Output Selection
→ Processing
→ Unified Results
→ Trust / Verification
→ Artifacts
→ History

## Transformation Inputs

The interface must support:

1. Source only
2. Prompt only
3. Source + Prompt

The user must not be forced to provide both.

## Outputs

1. Executive Summary
2. LinkedIn
3. Advisory
4. Presentation
5. X Thread
6. Infographic
7. Video Package

## Configuration

The interface supports:

- Audience
- Tone
- Language
- Detail
- Objective
- Style

Languages:

- English
- Hindi
- Spanish
- French
- German
- Portuguese
- Chinese
- Arabic
- Japanese
- Korean
- Custom

## Trust and Security

The existing product includes backend-backed security and trust features
such as:

- authentication
- RBAC
- ownership isolation
- request validation
- malware scanning
- PII detection
- prompt-injection defense
- RAG/source grounding
- evidence verification
- cross-output consistency
- SHA-256 artifact integrity
- provenance

The frontend must never invent security states.

## Theme

The application supports:

- Light
- Dark
- System

## Design Direction

The visual direction is inspired by modern AI creation workspaces and
Canva/Magic Studio-style simplicity.

Do not copy Canva branding, logos, proprietary assets, or exact UI text.

TransformIQ must retain its own professional enterprise identity.

## Implementation Rule

Do not blindly copy Stitch-generated application code into the existing
frontend.

Instead, use the Stitch screens as the visual reference and implement
the design using the existing TransformIQ architecture and components.

Do not modify the backend merely to reproduce a visual design.