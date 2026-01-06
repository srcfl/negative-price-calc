"use client";

import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Button,
  Checkbox,
} from "@sourceful-energy/ui";
import { toast } from "sonner";
import { Mail, Loader2 } from "lucide-react";

interface EmailCaptureProps {
  onEmailSubmitted: () => void;
  isAnalyzing: boolean;
}

const FORMSPARK_FORM_ID = "ExsKPPKKy";

export function EmailCapture({ onEmailSubmitted, isAnalyzing }: EmailCaptureProps) {
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [acceptMarketing, setAcceptMarketing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!email) {
      toast.error("Vänligen ange din e-postadress");
      return;
    }

    setIsSubmitting(true);

    try {
      const response = await fetch(
        `https://submit-form.com/${FORMSPARK_FORM_ID}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({
            email,
            company: company || "Ej angivet",
            acceptMarketing,
            source: "Negativa Prisanalyseraren",
            timestamp: new Date().toISOString(),
          }),
        }
      );

      if (!response.ok) {
        throw new Error("Failed to submit form");
      }

      toast.success("Tack! Din analys startar nu...");
      onEmailSubmitted();
    } catch {
      toast.error("Något gick fel. Försök igen.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card className="border-primary/20">
      <CardHeader className="pb-4">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-primary/10">
            <Mail className="h-5 w-5 text-primary" />
          </div>
          <div>
            <CardTitle className="text-lg">Få din analys</CardTitle>
            <CardDescription>
              Ange din e-post för att starta analysen
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">E-postadress *</Label>
            <Input
              id="email"
              type="email"
              placeholder="din@email.se"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={isSubmitting || isAnalyzing}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="company">Företag (valfritt)</Label>
            <Input
              id="company"
              type="text"
              placeholder="Ditt företag"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              disabled={isSubmitting || isAnalyzing}
            />
          </div>

          <div className="flex items-start space-x-2">
            <Checkbox
              id="marketing"
              checked={acceptMarketing}
              onCheckedChange={(checked) => setAcceptMarketing(checked === true)}
              disabled={isSubmitting || isAnalyzing}
            />
            <label
              htmlFor="marketing"
              className="text-sm text-muted-foreground leading-tight cursor-pointer"
            >
              Jag vill få tips och nyheter om energioptimering från Sourceful Energy
            </label>
          </div>

          <Button
            type="submit"
            className="w-full"
            disabled={isSubmitting || isAnalyzing || !email}
          >
            {isSubmitting || isAnalyzing ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                {isAnalyzing ? "Analyserar..." : "Skickar..."}
              </>
            ) : (
              "Analysera med AI-sammanfattning"
            )}
          </Button>

          <p className="text-xs text-muted-foreground text-center">
            Genom att klicka accepterar du vår{" "}
            <a href="https://sourceful.energy/privacy" className="text-primary hover:underline">
              integritetspolicy
            </a>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
