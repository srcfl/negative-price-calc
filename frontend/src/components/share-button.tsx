"use client";

import { useState, useCallback } from "react";
import { Button } from "@sourceful-energy/ui";
import { Share2, Check, Copy } from "lucide-react";
import { toast } from "sonner";

interface ShareButtonProps {
  resultId: string;
}

export function ShareButton({ resultId }: ShareButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleShare = useCallback(async () => {
    const url = `${window.location.origin}/r/${resultId}`;

    try {
      // Try native share first (mobile)
      if (navigator.share) {
        await navigator.share({
          title: "Negativa Prisanalyseraren - Resultat",
          text: "Se min elprissanalys",
          url,
        });
        return;
      }

      // Fallback to clipboard
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("Länk kopierad!");

      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      // If clipboard fails, show URL in a toast
      if (err instanceof Error && err.name !== "AbortError") {
        toast.info(`Länk: ${url}`);
      }
    }
  }, [resultId]);

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={handleShare}
      className="gap-2"
    >
      {copied ? (
        <>
          <Check className="h-4 w-4 text-primary" />
          Kopierad!
        </>
      ) : (
        <>
          <Share2 className="h-4 w-4" />
          Dela
        </>
      )}
    </Button>
  );
}
