import { NextRequest, NextResponse } from "next/server";

/**
 * Dummy signup endpoint — mirrors the response shape of the real backend's
 * POST /auth/register (backend/routers/auth.py -> TokenResponse) so the
 * frontend contract stays stable once this is swapped for a proxy call to
 * the FastAPI service.
 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);

  const requiredFields = ["name", "email", "password", "year", "goal", "targetRole"];
  const missing = !body || requiredFields.some((field) => typeof body[field] !== "string" || body[field].trim() === "");

  if (missing) {
    return NextResponse.json({ detail: "Missing or invalid fields." }, { status: 422 });
  }

  if (body.password.length < 8) {
    return NextResponse.json(
      { detail: "Password must be at least 8 characters." },
      { status: 422 }
    );
  }

  return NextResponse.json(
    {
      token: `dummy-token-${Date.now()}`,
      token_type: "bearer",
    },
    { status: 201 }
  );
}
