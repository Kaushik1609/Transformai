# KaryaSetu AI — Architecture Animation Voice-Over Asset Guide

## Target Audio File

- **Expected Path:** `frontend/public/audio/karyasetu-architecture-voiceover.mp3`
- **URL Path in App:** `/audio/karyasetu-architecture-voiceover.mp3`
- **Target Duration:** Approximately 38–40 seconds (1x playback speed)

## Narration Tone and Style

- **Tone:** Calm, confident, technical, clear, concise enterprise narration.
- **Pacing:** Normal conversational pace (~130–145 words per minute), suitable for SIH presentation / technical evaluation.
- **Audio Specs:** 44.1 kHz / 48 kHz stereo, 192 kbps MP3 format, normalized to -14 LUFS (EBU R128 standard).

## Voice-Over Script & Scene Timecodes

| Timecode | Scene | Script |
|---|---|---|
| **00:00 – 00:05** | Scene 1 · Source Anchoring | *"KaryaSetu AI starts with one trusted source of information."* |
| **00:05 – 00:10** | Scene 2 · Perimeter & Posture | *"The source is validated, secured, classified, and governed by policy."* |
| **00:10 – 00:15** | Scene 3 · Routing Governance | *"Policy determines whether processing uses cloud, local, or offline AI."* |
| **00:15 – 00:21** | Scene 4 · Evidence Chain | *"Relevant evidence is retrieved to ground the transformation in trusted source information."* |
| **00:21 – 00:27** | Scene 5 · Multi-Channel Synthesis | *"That trusted context is transformed into multiple audience-specific outputs."* |
| **00:27 – 00:33** | Scene 6 · Release Gating | *"Each output is verified and passes the required approval and dissemination controls."* |
| **00:33 – 00:38** | Scene 7 · Cryptographic Seal | *"Provenance, SHA-256 integrity, and Ed25519 signatures make the artifacts verifiable."* |
| **00:38 – 00:40** | Scene 8 · Platform Hero | *"One trusted source. Many verified, controlled artifacts."* |

## Fallback Behavior

If `karyasetu-architecture-voiceover.mp3` is not present, the `ArchitectureDemo` component falls back gracefully without throwing errors or interrupting the visual pipeline, and presents synchronized Closed Captions (CC) for full accessibility.
