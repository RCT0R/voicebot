"""Provision LiveKit inbound routing for a Vobiz phone number.

Run this once after creating the Vobiz SIP trunk and number. The script is
idempotent: it reuses an inbound trunk that already claims the number and reuses
a dispatch rule that already targets this agent. It never deletes anything.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from livekit import api

from config import ConfigError, load_environment
from telephony import derive_sip_endpoint, normalize_phone

SETUP_AGENT_NAME_RE = r"^[A-Za-z0-9_-]{1,64}$"
SETUP_ROOM_PREFIX_RE = r"^[A-Za-z0-9_-]{0,32}$"


@dataclass(frozen=True)
class SetupConfig:
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    inbound_number: str
    agent_name: str = "receptionist"
    allowed_addresses: tuple[str, ...] = ()
    auth_username: str = ""
    auth_password: str = ""
    room_prefix: str = "call-"
    max_call_duration_seconds: int = 600
    krisp_enabled: bool = True
    sip_uri_override: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SetupConfig:
        import re

        env = env if env is not None else os.environ
        missing: list[str] = []
        errors: list[str] = []

        def required(name: str) -> str:
            value = (env.get(name) or "").strip()
            if not value:
                missing.append(name)
            return value

        url = required("LIVEKIT_URL")
        key = required("LIVEKIT_API_KEY")
        secret = required("LIVEKIT_API_SECRET")
        sip_uri = required("LIVEKIT_SIP_URI")
        raw_number = required("VOBIZ_INBOUND_NUMBER")
        number = normalize_phone(raw_number)
        if raw_number and not number:
            errors.append("VOBIZ_INBOUND_NUMBER must be a valid E.164 number")

        agent_name = (env.get("AGENT_NAME") or "receptionist").strip()
        if not re.fullmatch(SETUP_AGENT_NAME_RE, agent_name):
            errors.append("AGENT_NAME must contain only letters, numbers, hyphens, and underscores")

        room_prefix = (env.get("ROOM_PREFIX") or "call-").strip()
        if not re.fullmatch(SETUP_ROOM_PREFIX_RE, room_prefix):
            errors.append("ROOM_PREFIX must contain only letters, numbers, hyphens, and underscores")

        raw_addresses = (env.get("INBOUND_SIP_ALLOWED_ADDRESSES") or "").strip()
        addresses = tuple(
            item.strip() for item in raw_addresses.split(",") if item.strip()
        )
        import ipaddress

        for address in addresses:
            try:
                ipaddress.ip_network(address, strict=False)
            except ValueError:
                errors.append(
                    "INBOUND_SIP_ALLOWED_ADDRESSES must be a comma-separated list of IP addresses or CIDR ranges"
                )
                break

        auth_username = (env.get("INBOUND_SIP_AUTH_USERNAME") or "").strip()
        auth_password = (env.get("INBOUND_SIP_AUTH_PASSWORD") or "").strip()
        if bool(auth_username) != bool(auth_password):
            errors.append(
                "INBOUND_SIP_AUTH_USERNAME and INBOUND_SIP_AUTH_PASSWORD must be set together"
            )

        try:
            max_duration = int((env.get("MAX_CALL_DURATION_SECONDS") or "600").strip())
        except ValueError:
            errors.append("MAX_CALL_DURATION_SECONDS must be an integer")
            max_duration = 600
        if not 30 <= max_duration <= 3600:
            errors.append("MAX_CALL_DURATION_SECONDS must be between 30 and 3600")

        if missing or errors:
            parts: list[str] = []
            if missing:
                parts.append(
                    "missing required environment variables: " + ", ".join(dict.fromkeys(missing))
                )
            parts.extend(errors)
            raise ConfigError("Invalid setup configuration: " + "; ".join(parts))

        return cls(
            livekit_url=url.rstrip("/"),
            livekit_api_key=key,
            livekit_api_secret=secret,
            inbound_number=number or "",
            agent_name=agent_name,
            allowed_addresses=addresses,
            auth_username=auth_username,
            auth_password=auth_password,
            room_prefix=room_prefix,
            max_call_duration_seconds=max_duration,
            krisp_enabled=(env.get("NOISE_CANCELLATION") or "true").strip().lower()
            not in {"0", "false", "no", "off"},
            sip_uri_override=sip_uri,
        )


@dataclass(frozen=True)
class InboundPlan:
    create_trunk: bool
    trunk_id: str | None
    create_dispatch_rule: bool
    dispatch_rule_id: str | None
    warnings: tuple[str, ...] = ()


def plan_inbound(
    existing_trunks: Sequence[Mapping[str, Any]],
    existing_rules: Sequence[Mapping[str, Any]],
    *,
    number: str,
    agent_name: str,
) -> InboundPlan:
    """Decide which LiveKit objects to create without changing the project."""
    warnings: list[str] = []
    matching_trunks = [
        trunk for trunk in existing_trunks if number in (trunk.get("numbers") or [])
    ]
    if len(matching_trunks) > 1:
        warnings.append(
            "Multiple inbound trunks claim this number. The first one is reused; remove duplicates manually."
        )

    if not matching_trunks:
        return InboundPlan(
            create_trunk=True,
            trunk_id=None,
            create_dispatch_rule=True,
            dispatch_rule_id=None,
            warnings=tuple(warnings),
        )

    trunk_id = str(matching_trunks[0]["id"])
    bound_rules = [
        rule
        for rule in existing_rules
        if trunk_id in [str(value) for value in (rule.get("trunk_ids") or [])]
    ]
    matching_rules = [
        rule for rule in bound_rules if agent_name in (rule.get("agent_names") or [])
    ]
    if matching_rules:
        return InboundPlan(
            create_trunk=False,
            trunk_id=trunk_id,
            create_dispatch_rule=False,
            dispatch_rule_id=str(matching_rules[0]["id"]),
            warnings=tuple(warnings),
        )
    if bound_rules:
        warnings.append(
            "A dispatch rule is already bound to this trunk but does not target "
            f"agent '{agent_name}'. Update that rule manually or remove it. No new rule was created."
        )
        return InboundPlan(
            create_trunk=False,
            trunk_id=trunk_id,
            create_dispatch_rule=False,
            dispatch_rule_id=None,
            warnings=tuple(warnings),
        )
    return InboundPlan(
        create_trunk=False,
        trunk_id=trunk_id,
        create_dispatch_rule=True,
        dispatch_rule_id=None,
        warnings=tuple(warnings),
    )


def build_trunk_info(cfg: SetupConfig) -> api.SIPInboundTrunkInfo:
    kwargs: dict[str, Any] = {
        "name": "AI receptionist inbound",
        "numbers": [cfg.inbound_number],
        "allowed_addresses": list(cfg.allowed_addresses) or ["0.0.0.0/0"],
        "krisp_enabled": cfg.krisp_enabled,
        "max_call_duration": timedelta(seconds=cfg.max_call_duration_seconds + 30),
    }
    if cfg.auth_username and cfg.auth_password:
        kwargs["auth_username"] = cfg.auth_username
        kwargs["auth_password"] = cfg.auth_password
    return api.SIPInboundTrunkInfo(**kwargs)


def build_dispatch_rule(cfg: SetupConfig, trunk_id: str) -> api.SIPDispatchRuleInfo:
    return api.SIPDispatchRuleInfo(
        name="AI receptionist inbound dispatch",
        trunk_ids=[trunk_id],
        rule=api.SIPDispatchRule(
            dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                room_prefix=cfg.room_prefix,
            )
        ),
        room_config=api.RoomConfiguration(
            agents=[
                api.RoomAgentDispatch(
                    agent_name=cfg.agent_name,
                    metadata=json.dumps({"direction": "inbound"}),
                )
            ]
        ),
    )


def _trunk_dicts(trunks: Any) -> list[dict[str, Any]]:
    return [
        {"id": trunk.sip_trunk_id, "numbers": list(trunk.numbers), "name": trunk.name}
        for trunk in trunks.items
    ]


def _rule_dicts(rules: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": rule.sip_dispatch_rule_id,
            "trunk_ids": list(rule.trunk_ids),
            "agent_names": [agent.agent_name for agent in rule.room_config.agents],
            "name": rule.name,
        }
        for rule in rules.items
    ]


def _print_plan(plan: InboundPlan) -> None:
    print("Inbound routing plan")
    print(f"  Create inbound trunk: {'yes' if plan.create_trunk else 'no'}")
    if plan.trunk_id:
        print(f"  Reuse trunk: {plan.trunk_id}")
        print("  Review the existing trunk's allowed addresses in LiveKit before production.")
    print(f"  Create dispatch rule: {'yes' if plan.create_dispatch_rule else 'no'}")
    if plan.dispatch_rule_id:
        print(f"  Reuse dispatch rule: {plan.dispatch_rule_id}")
        print("  Existing rule settings are unchanged; verify its room prefix and agent name.")
    for warning in plan.warnings:
        print(f"  Warning: {warning}")


async def ensure_inbound(cfg: SetupConfig, *, dry_run: bool = False) -> None:
    sip_endpoint = derive_sip_endpoint(cfg.livekit_url, cfg.sip_uri_override or None)
    print(f"LiveKit SIP endpoint: {sip_endpoint}")
    print(f"Vobiz number: {cfg.inbound_number}")
    print(f"Agent dispatch name: {cfg.agent_name}")
    if not cfg.allowed_addresses:
        print(
            "Warning: INBOUND_SIP_ALLOWED_ADDRESSES is empty, so LiveKit accepts SIP "
            "traffic from any source. Restrict this to Vobiz signalling addresses in production."
        )
    if cfg.auth_username:
        print(
            "Warning: inbound SIP digest authentication is enabled. Vobiz's LiveKit "
            "guide uses IP allowlisting; do not copy the outbound Vobiz username/password "
            "here unless Vobiz confirms inbound digest auth."
        )
    if dry_run:
        print("\nDry run: no LiveKit objects were created.")
        print("Inbound trunk configuration:")
        print(build_trunk_info(cfg))
        print("\nDispatch rule configuration (after a trunk exists):")
        print(build_dispatch_rule(cfg, "<trunk-id>"))
        return

    lk = api.LiveKitAPI(
        url=cfg.livekit_url,
        api_key=cfg.livekit_api_key,
        api_secret=cfg.livekit_api_secret,
    )
    try:
        trunks = await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        rules = await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        plan = plan_inbound(
            _trunk_dicts(trunks),
            _rule_dicts(rules),
            number=cfg.inbound_number,
            agent_name=cfg.agent_name,
        )
        _print_plan(plan)

        trunk_id = plan.trunk_id
        if plan.create_trunk:
            trunk = await lk.sip.create_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(trunk=build_trunk_info(cfg))
            )
            trunk_id = trunk.sip_trunk_id
            print(f"Created inbound trunk: {trunk_id}")

        rule_id = plan.dispatch_rule_id
        if plan.create_dispatch_rule and trunk_id:
            rule = await lk.sip.create_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(
                    dispatch_rule=build_dispatch_rule(cfg, trunk_id)
                )
            )
            rule_id = rule.sip_dispatch_rule_id
            print(f"Created dispatch rule: {rule_id}")

        print("\nNext steps")
        print("1. In the Vobiz Console, open SIP Trunk, edit the trunk for this number,")
        print("   and set the inbound destination to the SIP endpoint below.")
        print("   Do not add the sip: prefix.")
        print(f"   {sip_endpoint}")
        print("2. Confirm the number is linked to that trunk and the trunk has an active balance.")
        print("3. For an Indian number, complete the provider's KYC and inbound enablement.")
        print(f"4. Call {cfg.inbound_number} and check the agent logs for call_started.")
        print(
            "5. If the caller hears silence, confirm the dispatch rule targets "
            f"agent '{cfg.agent_name}' and that the worker is running."
        )
    finally:
        await lk.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create LiveKit inbound routing for Vobiz.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the intended LiveKit configuration without creating anything.",
    )
    args = parser.parse_args()

    load_environment()
    try:
        cfg = SetupConfig.from_env()
        asyncio.run(ensure_inbound(cfg, dry_run=args.dry_run))
    except (ConfigError, ValueError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(2)
    except Exception as exc:
        from logging_setup import redact_secrets

        print(f"Error: LiveKit provisioning failed: {redact_secrets(str(exc))}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
