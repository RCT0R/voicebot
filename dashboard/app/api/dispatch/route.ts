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

export async function POST(request: Request): Promise<NextResponse> {
  try {
    const body = await request.json().catch(() => null);
    if (!body || typeof body !== 'object') {
      return NextResponse.json({ error: 'A JSON body is required.' }, { status: 400 });
    }

    const input = body as Record<string, unknown>;
    const phoneNumber = normalizeE164(input.phoneNumber);
    if (!phoneNumber) {
      return NextResponse.json(
        { error: 'Phone number must be in E.164 form, for example +918071387434.' },
        { status: 400 },
      );
    }

    const trunkId = getOutboundTrunkId();
    if (!trunkId) {
      return NextResponse.json({ error: 'Outbound trunk is not configured.' }, { status: 503 });
    }

    const roomName = `outbound-${randomUUID()}`;
    const metadata = JSON.stringify({
      phone_number: phoneNumber,
      direction: 'outbound',
      dial: false,
      user_prompt: clampText(input.prompt, 2000),
      model_provider: clampText(input.modelProvider, 40),
      voice_id: clampText(input.voice, 40),
      agent_name: getAgentName(),
    });

    // Create the room first so its metadata is available to the agent. The
    // agent must not dial again after the SIP participant is created here.
    await getRoomService().createRoom({
      name: roomName,
      metadata,
      emptyTimeout: 300,
    });

    // The worker uses an explicit dispatch name, so a room alone does not
    // start it. Dispatch it before the SIP participant joins.
    const dispatch = await getAgentDispatchClient().createDispatch(
      roomName,
      getAgentName(),
      { metadata },
    );

    const info = await getSipClient().createSipParticipant(trunkId, phoneNumber, roomName, {
      participantIdentity: `sip_${randomUUID()}`,
      participantName: 'Caller',
      ringingTimeout: 30,
      maxCallDuration: getSipMaxCallDuration(),
    });

    return NextResponse.json({
      success: true,
      roomName,
      dispatchId: dispatch.id,
      sipCallId: info.sipCallId,
    });
  } catch {
    // Do not return provider error details or credentials to the browser.
    console.error('Outbound dispatch failed.');
    return NextResponse.json({ error: 'Could not dispatch the call.' }, { status: 500 });
  }
}
