import { NextRequest, NextResponse } from 'next/server';

export const config = {
  // Protect the page and API routes. Public image assets stay cacheable.
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)',
  ],
};

function safeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  let difference = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (a[index] ?? 0) ^ (b[index] ?? 0);
  }
  return difference === 0;
}

function challenge(): NextResponse {
  return new NextResponse('Authentication required.', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Receptionist dashboard", charset="UTF-8"',
      'Cache-Control': 'no-store',
    },
  });
}

export function proxy(request: NextRequest): NextResponse {
  const username = process.env.DASHBOARD_USERNAME;
  const password = process.env.DASHBOARD_PASSWORD;

  if (!username || !password) {
    return new NextResponse(
      'Dashboard authentication is not configured. Set DASHBOARD_USERNAME and DASHBOARD_PASSWORD.',
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }

  const authorization = request.headers.get('authorization');
  if (!authorization?.startsWith('Basic ')) {
    return challenge();
  }

  let decoded: string;
  try {
    decoded = atob(authorization.slice(6));
  } catch {
    return challenge();
  }

  const separator = decoded.indexOf(':');
  if (separator < 0) {
    return challenge();
  }

  const suppliedUser = decoded.slice(0, separator);
  const suppliedPassword = decoded.slice(separator + 1);
  if (!safeEqual(suppliedUser, username) || !safeEqual(suppliedPassword, password)) {
    return challenge();
  }

  const response = NextResponse.next();
  response.headers.set('Cache-Control', 'no-store');
  return response;
}
