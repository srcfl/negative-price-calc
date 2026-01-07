import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8080";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;

    const backendResponse = await fetch(`${BACKEND_URL}/results/${id}`, {
      headers: {
        "Accept": "application/json",
      },
    });

    if (!backendResponse.ok) {
      return new Response(
        JSON.stringify({ error: "Result not found" }),
        {
          status: backendResponse.status,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    const data = await backendResponse.json();
    return Response.json(data);
  } catch (error) {
    console.error("Proxy error:", error);
    return new Response(
      JSON.stringify({ error: "Failed to fetch result" }),
      {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
}
