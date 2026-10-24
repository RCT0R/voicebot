from __future__ import annotations

import json

import pytest

from config import ConfigError
from setup_inbound import (
    SetupConfig,
    build_dispatch_rule,
    build_trunk_info,
    plan_inbound,
)

SETUP_ENV = {
    "LIVEKIT_URL": "wss://demo-project.livekit.cloud",
    "LIVEKIT_API_KEY": "lk_test_key",
    "LIVEKIT_API_SECRET": "lk_test_secret_do_not_use",
    "VOBIZ_INBOUND_NUMBER": "+918071387434",
    "AGENT_NAME": "receptionist",
}


def test_setup_config_does_not_require_speech_provider_keys():
    cfg = SetupConfig.from_env(SETUP_ENV)
    assert cfg.inbound_number == "+918071387434"
    assert cfg.agent_name == "receptionist"


def test_setup_config_rejects_invalid_inbound_number():
    env = dict(SETUP_ENV)
    env["VOBIZ_INBOUND_NUMBER"] = "8071387434"
    with pytest.raises(ConfigError, match="VOBIZ_INBOUND_NUMBER"):
        SetupConfig.from_env(env)


def test_setup_config_rejects_invalid_allowed_address():
    env = dict(SETUP_ENV)
    env["INBOUND_SIP_ALLOWED_ADDRESSES"] = "phone.example.com"
    with pytest.raises(ConfigError, match="INBOUND_SIP_ALLOWED_ADDRESSES"):
        SetupConfig.from_env(env)


def test_plan_creates_trunk_and_rule_when_nothing_exists():
    plan = plan_inbound([], [], number="+918071387434", agent_name="receptionist")

    assert plan.create_trunk is True
    assert plan.create_dispatch_rule is True
    assert plan.trunk_id is None
    assert plan.warnings == ()


def test_plan_reuses_trunk_and_creates_missing_rule():
    plan = plan_inbound(
        [{"id": "ST_existing", "numbers": ["+918071387434"]}],
        [],
        number="+918071387434",
        agent_name="receptionist",
    )

    assert plan.create_trunk is False
    assert plan.trunk_id == "ST_existing"
    assert plan.create_dispatch_rule is True


def test_plan_reuses_matching_trunk_and_rule():
    plan = plan_inbound(
        [{"id": "ST_existing", "numbers": ["+918071387434"]}],
        [
            {
                "id": "SDR_existing",
                "trunk_ids": ["ST_existing"],
                "agent_names": ["receptionist"],
            }
        ],
        number="+918071387434",
        agent_name="receptionist",
    )

    assert plan.create_trunk is False
    assert plan.create_dispatch_rule is False
    assert plan.dispatch_rule_id == "SDR_existing"


def test_plan_does_not_create_a_second_rule_for_another_agent():
    plan = plan_inbound(
        [{"id": "ST_existing", "numbers": ["+918071387434"]}],
        [
            {
                "id": "SDR_other",
                "trunk_ids": ["ST_existing"],
                "agent_names": ["some-other-agent"],
            }
        ],
        number="+918071387434",
        agent_name="receptionist",
    )

    assert plan.create_trunk is False
    assert plan.create_dispatch_rule is False
    assert plan.dispatch_rule_id is None
    assert any("does not target" in warning for warning in plan.warnings)


def test_trunk_configuration_sets_number_and_hard_duration_limit():
    cfg = SetupConfig.from_env({**SETUP_ENV, "MAX_CALL_DURATION_SECONDS": "600"})
    trunk = build_trunk_info(cfg)

    assert list(trunk.numbers) == ["+918071387434"]
    assert trunk.max_call_duration.seconds == 630
    assert trunk.krisp_enabled is True


def test_dispatch_rule_targets_the_configured_agent():
    cfg = SetupConfig.from_env(SETUP_ENV)
    rule = build_dispatch_rule(cfg, "ST_existing")

    assert list(rule.trunk_ids) == ["ST_existing"]
    assert rule.rule.dispatch_rule_individual.room_prefix == "call-"
    assert rule.room_config.agents[0].agent_name == "receptionist"
    assert json.loads(rule.room_config.agents[0].metadata) == {"direction": "inbound"}
