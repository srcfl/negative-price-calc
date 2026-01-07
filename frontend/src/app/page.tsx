"use client";

import { useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Label,
  Button,
} from "@sourceful-energy/ui";
import { toast } from "sonner";
import { X } from "lucide-react";
import { Header } from "@/components/header";
import { FileUpload } from "@/components/file-upload";
import { EmailCapture } from "@/components/email-capture";
import { StreamingTerminal, LogEntry } from "@/components/streaming-terminal";

const AREA_CODES = {
  SE_1: "Norra Sverige (Luleå)",
  SE_2: "Mellersta Sverige (Sundsvall)",
  SE_3: "Mellersta Sverige (Stockholm)",
  SE_4: "Södra Sverige (Malmö)",
};

// API routes are proxied through Next.js - no CORS issues

interface AnalysisResponse {
  success: boolean;
  analysis: Record<string, unknown>;
  metadata: {
    filename: string;
    granularity: string;
    area: string;
    currency: string;
    analyzed_at: string;
    ai_enabled: boolean;
  };
  result_id?: string;
  error?: string;
}

export default function Home() {
  const router = useRouter();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedArea, setSelectedArea] = useState("SE_4");
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [showTerminal, setShowTerminal] = useState(false);
  const [hasError, setHasError] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const addLog = useCallback((type: LogEntry["type"], message: string) => {
    const timestamp = new Date().toLocaleTimeString("sv-SE", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    setLogs((prev) => [...prev, { timestamp, type, message }]);
  }, []);

  const handleAnalyze = useCallback(async () => {
    if (!selectedFile) {
      toast.error("Välj en fil först");
      return;
    }

    setIsAnalyzing(true);
    setShowTerminal(true);
    setLogs([]);
    setHasError(false);

    // Abort any previous request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    try {
      const formData = new FormData();
      formData.append("production_file", selectedFile);
      formData.append("area", selectedArea);

      addLog("info", `Startar analys av ${selectedFile.name}...`);

      const response = await fetch("/api/analyze/stream", {
        method: "POST",
        body: formData,
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error("Kunde inte starta analysen");
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("Streaming stöds inte");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));

              if (data.type === "result") {
                // Redirect to permalink
                const resultId = data.data?.result_id;
                if (resultId) {
                  addLog("success", "Omdirigerar till resultat...");
                  router.push(`/r/${resultId}`);
                }
              } else if (data.type === "error") {
                addLog("error", data.message);
                setHasError(true);
              } else {
                addLog(data.type, data.message);
              }
            } catch {
              // Ignore parse errors
            }
          }
        }
      }
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        addLog("info", "Analys avbruten");
        return;
      }
      const message = error instanceof Error ? error.message : "Ett fel uppstod";
      addLog("error", message);
      setHasError(true);
    } finally {
      setIsAnalyzing(false);
    }
  }, [selectedFile, selectedArea, addLog, router]);

  const handleCancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setShowTerminal(false);
    setIsAnalyzing(false);
    setLogs([]);
    setHasError(false);
  }, []);

  return (
    <div className="min-h-screen flex flex-col">
      <Header />

      <main className="flex-1 container mx-auto px-4 py-8">
        {showTerminal ? (
          // Analyze mode - show terminal prominently
          <div className="max-w-3xl mx-auto space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold">Analyserar {selectedFile?.name}</h2>
                <p className="text-sm text-muted-foreground">
                  Elområde: {selectedArea}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCancel}
                disabled={!isAnalyzing && !hasError}
              >
                <X className="h-4 w-4 mr-2" />
                {hasError ? "Stäng" : "Avbryt"}
              </Button>
            </div>

            <StreamingTerminal logs={logs} isActive={isAnalyzing} />

            {hasError && (
              <div className="text-center">
                <Button variant="outline" onClick={handleCancel}>
                  Försök igen
                </Button>
              </div>
            )}
          </div>
        ) : (
          // Upload mode - show hero and form
          <div className="max-w-2xl mx-auto space-y-8">
            {/* Hero Section */}
            <div className="text-center space-y-4">
              <h1 className="text-4xl font-bold tracking-tight">
                <span className="text-foreground">Negativa </span>
                <span className="text-primary">Prisanalyseraren</span>
              </h1>
              <p className="text-lg text-muted-foreground max-w-xl mx-auto">
                Upptäck hur negativa elpriser påverkar din solexport och få
                AI-drivna insikter för att optimera din energistrategi.
              </p>
            </div>

            {/* Upload Form */}
            <div className="space-y-6">
              <FileUpload
                selectedFile={selectedFile}
                onFileSelect={setSelectedFile}
              />

              <div className="space-y-2">
                <Label>Svenskt elområde</Label>
                <Select value={selectedArea} onValueChange={setSelectedArea}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(AREA_CODES).map(([code, name]) => (
                      <SelectItem key={code} value={code}>
                        {code} - {name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {selectedFile && (
                <EmailCapture
                  onEmailSubmitted={handleAnalyze}
                  isAnalyzing={isAnalyzing}
                />
              )}
            </div>

            {/* Info Section */}
            <div className="rounded-lg border border-border/50 bg-muted/30 p-6 space-y-4">
              <h3 className="font-semibold text-foreground">Så här fungerar det</h3>
              <ol className="list-decimal list-inside space-y-2 text-sm text-muted-foreground">
                <li>
                  <span className="text-foreground">Hämta din exportdata</span> – Logga in på Mina Sidor hos ditt nätbolag eller elbolag och exportera din mätardata (ofta CSV eller Excel).
                </li>
                <li>
                  <span className="text-foreground">Ladda upp filen</span> – Välj filen ovan. Verktyget försöker automatiskt tolka formatet.
                </li>
                <li>
                  <span className="text-foreground">Få din analys</span> – Vi matchar din export med historiska spotpriser och räknar ut vad din solel var värd.
                </li>
              </ol>

              <div className="pt-2 border-t border-border/50 space-y-2 text-sm text-muted-foreground">
                <p>
                  <strong className="text-foreground">Varför är detta viktigt?</strong> Sedan 1 januari 2026 finns inte längre skattereduktionen på 60 öre/kWh för solel.
                  Nu är det spotpriset som avgör vad din export är värd – och vid negativa priser kan du till och med förlora pengar på att exportera.
                </p>
                <p>
                  <strong className="text-foreground">Krav på data:</strong> Filen måste innehålla en kolumn med datum/tid och en kolumn med exporterad energi i kWh.
                  Bäst resultat med timdata eller 15-minutersdata.
                </p>
                <p className="text-xs italic">
                  Verktyget gör sitt bästa för att tolka olika filformat, men vi tar inget ansvar för analysens exakthet.
                </p>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-border/40 py-6">
        <div className="container mx-auto px-4 text-center text-sm text-muted-foreground">
          <p>
            Made with{" "}
            <span className="text-destructive">♥</span> in Kalmar, Sweden
          </p>
          <p className="mt-1">
            Powered by{" "}
            <a
              href="https://sourceful.energy"
              className="text-primary hover:underline"
              target="_blank"
              rel="noopener noreferrer"
            >
              Sourceful Energy
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}
