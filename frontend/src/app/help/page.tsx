/**
 * TransformIQ — Help & Documentation page.
 */
"use client";

import { AppShell } from "@/components/layout";
import { cn } from "@/lib/utils";
import { useState } from "react";

const FAQS = [
  {
    q: "What is TransformIQ?",
    a: "TransformIQ turns one source and/or one instruction into many communication formats at once.",
  },
  {
    q: "Do I need a source file?",
    a: "No. TransformIQ accepts a prompt alone, a source alone, or both. Attach a source for grounded, verifiable claims.",
  },
  {
    q: "Do I need to re-upload my source for each output?",
    a: "No. Add your source once, choose any number of outputs, and TransformIQ orchestrates them together.",
  },
  {
    q: "What output formats are supported?",
    a: "Summary, LinkedIn, Advisory, Presentation (PPTX), X Thread, Infographic, and Video package (storyboard + SRT).",
  },
  {
    q: "What file types can I upload?",
    a: "PDF, DOCX, and TXT files are supported.",
  },
];

export default function HelpPage() {
  const [open, setOpen] = useState<number | null>(0);

  return (
    <AppShell
      active="/help"
      title="Help & Documentation"
      subtitle="Everything you need to get the most from TransformIQ"
    >
      <div className="max-w-2xl space-y-6">
        <section>
          <h2 className="text-base font-semibold text-foreground">Getting started</h2>
          <ol className="mt-3 space-y-2 text-sm text-muted-foreground">
            <li className="flex gap-2"><span className="font-medium text-primary">1.</span> Open Home and describe what you want to create.</li>
            <li className="flex gap-2"><span className="font-medium text-primary">2.</span> Optionally add a source (PDF, DOCX or TXT) for grounded output.</li>
            <li className="flex gap-2"><span className="font-medium text-primary">3.</span> Choose a tone, audience and output language.</li>
            <li className="flex gap-2"><span className="font-medium text-primary">4.</span> Select one or more outputs and click Transform.</li>
            <li className="flex gap-2"><span className="font-medium text-primary">5.</span> Review each output&apos;s verification results (grounding, consistency, claims).</li>
            <li className="flex gap-2"><span className="font-medium text-primary">6.</span> Download available artifacts (text, PPTX, PNG, PDF, SRT), or copy text outputs.</li>
          </ol>
        </section>

        <section>
          <h2 className="text-base font-semibold text-foreground">FAQ</h2>
          <div className="mt-3 space-y-2">
            {FAQS.map((faq, i) => (
              <div key={i} className="rounded-lg border border-border bg-surface-elevated">
                <button
                  type="button"
                  onClick={() => setOpen(open === i ? null : i)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-foreground"
                  aria-expanded={open === i}
                >
                  {faq.q}
                  <span className={cn("text-muted-foreground transition-transform", open === i && "rotate-180")}>
                    ▾
                  </span>
                </button>
                {open === i && (
                  <p className="px-4 pb-3 text-sm text-muted-foreground">{faq.a}</p>
                )}
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-base font-semibold text-foreground">Troubleshooting</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            If a transformation partially fails, your completed outputs remain
            available. If a source fails to process, please try again with a
            supported file type.
          </p>
        </section>
      </div>
    </AppShell>
  );
}
