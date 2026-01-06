"use client";

import { useEffect, useState, useCallback, use } from "react";
import { Button } from "@sourceful-energy/ui";
import { toast } from "sonner";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { Header } from "@/components/header";
import { AnalysisResults } from "@/components/analysis-results";
import { ShareButton } from "@/components/share-button";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

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

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ResultPage({ params }: PageProps) {
  const { id } = use(params);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function fetchResult() {
      try {
        const response = await fetch(`${API_BASE_URL}/results/${id}`);
        const data = await response.json();

        if (!response.ok || data.error) {
          throw new Error(data.error || "Kunde inte hämta resultat");
        }

        setResult(data);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Ett fel uppstod";
        setError(message);
      } finally {
        setIsLoading(false);
      }
    }

    fetchResult();
  }, [id]);

  const handleDownloadXlsx = useCallback(async () => {
    if (!result) return;

    try {
      const response = await fetch(`${API_BASE_URL}/download_xlsx`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          analysis: result.analysis,
          metadata: result.metadata,
        }),
      });

      if (!response.ok) {
        throw new Error("Kunde inte ladda ner filen");
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `analysis_${new Date().toISOString().split("T")[0]}.xlsx`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch {
      toast.error("Kunde inte ladda ner Excel-filen");
    }
  }, [result]);

  const handleDownloadJson = useCallback(() => {
    if (!result) return;

    const blob = new Blob([JSON.stringify(result.analysis, null, 2)], {
      type: "application/json",
    });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `analysis_${new Date().toISOString().split("T")[0]}.json`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    document.body.removeChild(a);
  }, [result]);

  return (
    <div className="min-h-screen flex flex-col">
      <Header />

      <main className="flex-1 container mx-auto px-4 py-8">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center gap-4 py-16">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-muted-foreground">Laddar resultat...</p>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center gap-4 py-16">
            <p className="text-destructive">{error}</p>
            <Button variant="outline" asChild>
              <Link href="/">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Tillbaka till startsidan
              </Link>
            </Button>
          </div>
        ) : result ? (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <Button variant="ghost" size="sm" asChild>
                <Link href="/">
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  Ny analys
                </Link>
              </Button>
              <ShareButton resultId={id} />
            </div>

            <AnalysisResults
              data={result.analysis}
              metadata={result.metadata}
              onDownloadXlsx={handleDownloadXlsx}
              onDownloadJson={handleDownloadJson}
            />
          </div>
        ) : null}
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
