"use client";

import React from "react";

interface LaptopMockupProps {
  children: React.ReactNode;
  className?: string;
}

/**
 * Realistic MacBook-style laptop frame for displaying interactive product demos.
 * Includes aluminum lid bezel, centered FaceTime camera notch, perspective keyboard base,
 * thumb opener indent, and realistic contact drop-shadow.
 */
export function LaptopMockup({ children, className = "" }: LaptopMockupProps) {
  return (
    <div className={`relative w-full max-w-5xl mx-auto flex flex-col items-center select-none ${className}`}>
      {/* Laptop Lid (Screen & Bezel) */}
      <div className="relative w-full rounded-t-[22px] sm:rounded-t-[32px] md:rounded-t-[38px] p-[6px] sm:p-[10px] md:p-[12px] pb-0 bg-gradient-to-b from-[#323947] via-[#212735] to-[#121620] border-t border-x border-slate-500/30 shadow-2xl transition-all">
        {/* Inner Black Bezel */}
        <div className="relative w-full rounded-t-[16px] sm:rounded-t-[24px] md:rounded-t-[28px] bg-[#090c13] p-1.5 sm:p-2.5 md:p-3 pb-1 flex flex-col">
          {/* Top Bezel Center Camera Notch / Island */}
          <div className="relative mx-auto mb-1 flex items-center justify-center">
            <div className="w-16 sm:w-24 md:w-28 h-2.5 sm:h-3.5 bg-[#06080e] rounded-b-md border-b border-x border-slate-800/90 flex items-center justify-center gap-2 px-2 shadow-inner">
              {/* Camera Lens */}
              <div className="w-1.5 h-1.5 sm:w-2 sm:h-2 rounded-full bg-[#141923] border border-slate-700/80 flex items-center justify-center shadow-inner">
                <div className="w-0.5 h-0.5 rounded-full bg-blue-400/60" />
              </div>
              {/* Green indicator LED */}
              <div className="w-1 h-1 rounded-full bg-emerald-400/80 animate-pulse" />
            </div>
          </div>

          {/* Screen Display Area (16:10 Authentic MacBook Pro Aspect Ratio) */}
          <div className="relative w-full aspect-[16/10] overflow-hidden rounded-[8px] sm:rounded-[12px] md:rounded-[14px] bg-[#07090E] border border-slate-800/80 shadow-[inset_0_2px_8px_rgba(0,0,0,0.8)]">
            {children}

            {/* Subtle Screen Glass Glare / Reflection effect (top-right highlight) */}
            <div className="absolute inset-0 bg-gradient-to-br from-white/[0.03] via-transparent to-transparent pointer-events-none" />
          </div>
        </div>
      </div>

      {/* Laptop Hinge & Base Deck (Bottom Chassis) */}
      <div className="relative w-full flex flex-col items-center">
        {/* Recessed Dark Hinge */}
        <div className="w-[98%] h-1 sm:h-1.5 bg-[#07090e] border-t border-black/90 shadow-inner" />

        {/* Aluminum Lower Base Deck (Slightly wider for 3D perspective) */}
        <div className="relative w-[102%] sm:w-[103%] md:w-[103.5%] h-3.5 sm:h-5 md:h-6 rounded-b-[14px] sm:rounded-b-[20px] md:rounded-b-[24px] bg-gradient-to-b from-[#2e3544] via-[#202532] to-[#121620] border-t border-slate-400/25 border-b border-slate-700/40 shadow-[0_4px_12px_rgba(0,0,0,0.5)]">
          {/* Center Thumb Opener Notch */}
          <div className="w-16 sm:w-24 md:w-28 h-1 sm:h-1.5 mx-auto bg-[#07090e] rounded-b-md border-t border-white/10 shadow-inner" />
        </div>

        {/* Subtle Natural Desk Shadow */}
        <div className="w-[94%] h-2 bg-slate-900/15 dark:bg-black/60 blur-xs rounded-[100%] mx-auto -mt-0.5" />
        <div className="w-[86%] h-4 sm:h-6 bg-slate-900/10 dark:bg-black/40 blur-lg rounded-[100%] mx-auto -mt-0.5 pointer-events-none" />
      </div>
    </div>
  );
}
