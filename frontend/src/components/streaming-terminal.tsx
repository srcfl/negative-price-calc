"use client";

import { useEffect, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@sourceful-energy/ui";
import { Terminal } from "lucide-react";

export interface LogEntry {
  timestamp: string;
  type: "info" | "success" | "error" | "ai" | "progress";
  message: string;
}

interface StreamingTerminalProps {
  logs: LogEntry[];
  isActive: boolean;
}

function getLogColor(type: LogEntry["type"]): string {
  switch (type) {
    case "success":
      return "text-primary";
    case "error":
      return "text-destructive";
    case "ai":
      return "text-cyan-400";
    case "progress":
      return "text-yellow-400";
    default:
      return "text-muted-foreground";
  }
}

function getLogIcon(type: LogEntry["type"]): string {
  switch (type) {
    case "success":
      return "✓";
    case "error":
      return "✗";
    case "ai":
      return "◆";
    case "progress":
      return "►";
    default:
      return "○";
  }
}

export function StreamingTerminal({ logs, isActive }: StreamingTerminalProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <Card className="border-border/50 bg-[#0d0d0d]">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-primary" />
          <CardTitle className="text-sm font-medium">Analyslogg</CardTitle>
          {isActive && (
            <span className="flex items-center gap-1.5 ml-auto">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
              </span>
              <span className="text-xs text-muted-foreground">Analyserar...</span>
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div
          ref={scrollRef}
          className="h-64 overflow-y-auto font-mono text-xs p-4 space-y-1"
        >
          {logs.length === 0 ? (
            <div className="text-muted-foreground/50 italic">
              Väntar på analysstart...
            </div>
          ) : (
            logs.map((log, index) => (
              <div key={index} className="flex gap-2">
                <span className="text-muted-foreground/50 shrink-0">
                  {log.timestamp}
                </span>
                <span className={`shrink-0 ${getLogColor(log.type)}`}>
                  {getLogIcon(log.type)}
                </span>
                <span className={getLogColor(log.type)}>
                  {log.message}
                </span>
              </div>
            ))
          )}
          {isActive && (
            <div className="flex gap-2 animate-pulse">
              <span className="text-muted-foreground/50 shrink-0">
                {new Date().toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
              <span className="text-muted-foreground">_</span>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
