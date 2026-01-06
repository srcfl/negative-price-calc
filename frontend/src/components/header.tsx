"use client";

import Image from "next/image";
import { Zap } from "lucide-react";

export function Header() {
  return (
    <header className="border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto px-4 h-16 flex items-center justify-between">
        <a
          href="https://sourceful.energy"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          <div className="p-1.5 rounded-lg bg-primary">
            <Zap className="h-5 w-5 text-primary-foreground" />
          </div>
          <span className="text-xl font-bold text-primary">
            Sourceful Energy
          </span>
        </a>
        <nav className="flex items-center gap-4">
          <a
            href="https://sourceful.energy"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            target="_blank"
            rel="noopener noreferrer"
          >
            Om Sourceful
          </a>
        </nav>
      </div>
    </header>
  );
}
