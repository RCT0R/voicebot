import { AgentDispatchClient, RoomServiceClient, SipClient } from 'livekit-server-sdk';

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not configured.`);
  }
  return value;
}

export function getRoomService(): RoomServiceClient {
  return new RoomServiceClient(required('LIVEKIT_URL'), required('LIVEKIT_API_KEY'), required('LIVEKIT_API_SECRET'));
}

export function getSipClient(): SipClient {
  return new SipClient(required('LIVEKIT_URL'), required('LIVEKIT_API_KEY'), required('LIVEKIT_API_SECRET'));
}

export function getAgentDispatchClient(): AgentDispatchClient {
  return new AgentDispatchClient(required('LIVEKIT_URL'), required('LIVEKIT_API_KEY'), required('LIVEKIT_API_SECRET'));
}

export function getOutboundTrunkId(): string {
  return process.env.OUTBOUND_TRUNK_ID || process.env.VOBIZ_SIP_TRUNK_ID || '';
}

export function getAgentName(): string {
  return process.env.AGENT_NAME || 'receptionist';
}

export function getSipMaxCallDuration(): number {
  const configured = Number(process.env.MAX_CALL_DURATION_SECONDS ?? 600);
  const agentLimit = Number.isFinite(configured)
    ? Math.min(3600, Math.max(30, configured))
    : 600;
  return agentLimit + 30;
}
