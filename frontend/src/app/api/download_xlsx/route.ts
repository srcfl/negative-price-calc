import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8080";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const backendResponse = await fetch(`${BACKEND_URL}/download_xlsx`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!backendResponse.ok) {
      return new Response(
        JSON.stringify({ error: "Failed to generate Excel file" }),
        {
          status: backendResponse.status,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // Get the blob and forward with correct headers
    const blob = await backendResponse.blob();
    return new Response(blob, {
      headers: {
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition": 'attachment; filename="analysis.xlsx"',
      },
    });
  } catch (error) {
    console.error("Proxy error:", error);
    return new Response(
      JSON.stringify({ error: "Proxy request failed" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
}
