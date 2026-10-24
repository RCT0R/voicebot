import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';

import {
  getAgentDispatchClient,
  getAgentName,
  getOutboundTrunkId,
  getRoomService,
  getSipClient,
  getSipMaxCallDuration,
} from '@/lib/server-utils';
import { clampText, normalizeE164 } from '@/lib/validation';

const MAX_BULK_CALLS = 50;

export async function POST(request: Request): Promise<NextResponse> {
  try {
    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object') {
      return NextResponse.json({ error: 'A JSON body is required.' }, { status: 400 });
    }

    const input = body as Record<string, unknown>;
    if (!Array.isArray(input.numbers)) {
      return NextResponse.json({ error: 'numbers must be an array.' }, { status: 400 });
    }

    const numbers = Array.from(
      new Set(
        input.numbers
          .map((value) => normalizeE164(value))
          .filter((value): value is string => value !== null),
      ),
    ).slice(0, MAX_BULK_CALLS);

    if (numbers.length === 0) {
      return NextResponse.json(
        { error: 'Provide at least one E.164 phone number.' },
        { status: 400 },
      );
    }

    const trunkId = getOutboundTrunkId();
    if (!trunkId) {
      return NextResponse.json({ error: 'Outbound trunk is not configured.' }, { status: 503 });
    }

    const prompt = clampText(input.prompt, 2000);
    const roomService = getRoomService();
    const sipClient = getSipClient();
    const agentDispatchClient = getAgentDispatchClient();
    const agentName = getAgentName();
    const results: Array<Record<string, unknown>> = [];

    for (const phoneNumber of numbers) {
      const roomName = `outbound-${randomUUID()}`;
      const roomMetadata = JSON.stringify({
        phone_number: phoneNumber,
        direction: 'outbound',
        dial: false,
        user_prompt: prompt,
      });
      try {
        await roomService.createRoom({
          name: roomName,
          metadata: roomMetadata,
          emptyTimeout: 300,
        });
        const dispatch = await agentDispatchClient.createDispatch(roomName, agentName, {
          metadata: roomMetadata,
        });
        const info = await sipClient.createSipParticipant(trunkId, phoneNumber, roomName, {
          participantIdentity: `sip_${randomUUID()}`,
          participantName: 'Caller',
          ringingTimeout: 30,
          maxCallDuration: getSipMaxCallDuration(),
        });
        results.push({
          phoneNumber,
          status: 'dispatched',
          dispatchId: dispatch.id,
          id: info.sipCallId,
        });
      } catch {
        results.push({ phoneNumber, status: 'failed' });
      }
      await new Promise((resolve) => setTimeout(resolve, 200));
    }

    return NextResponse.json({
      success: true,
      message: `Processed ${numbers.length} numbers.`,
      results,
    });
  } catch {
    console.error('Bulk dispatch failed.');
    return NextResponse.json({ error: 'Could not process the call list.' }, { status: 500 });
  }
}
