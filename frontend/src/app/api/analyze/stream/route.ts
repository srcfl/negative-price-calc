import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8080";

export async function POST(request: NextRequest) {
  try {
    // Get the form data from the request
    const formData = await request.formData();

    // Forward the request to the backend
    const backendResponse = await fetch(`${BACKEND_URL}/analyze/stream`, {
      method: "POST",
      body: formData,
    });

    if (!backendResponse.ok) {
      return new Response(
        JSON.stringify({ error: "Backend request failed" }),
        {
          status: backendResponse.status,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // Stream the SSE response back to the client
    const stream = backendResponse.body;
    if (!stream) {
      return new Response(
        JSON.stringify({ error: "No response stream" }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    // Return the stream with SSE headers
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
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
