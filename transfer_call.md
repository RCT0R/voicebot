# SIP call transfer

Transfer is optional.
It is disabled by default because it depends on the Vobiz trunk supporting SIP REFER and on a destination number you control.

## Enable it

```dotenv
ENABLE_TRANSFER=true
DEFAULT_TRANSFER_NUMBER=+91XXXXXXXXXX
```

The destination must be E.164.
The agent also accepts a caller-supplied E.164 number through the `transfer_call` tool.
It rejects arbitrary SIP URIs.

Restart the agent after changing the environment.

## How it works

When the caller asks for a human, the model may call `transfer_call`.
The agent calls `JobContext.transfer_sip_participant` for the SIP participant in the current room.
LiveKit sends a SIP REFER to Vobiz.

The agent cannot confirm that the destination answered.
It tells the caller that the transfer started, not that a person answered.

## Requirements

- The Vobiz trunk has call transfer or SIP REFER enabled.
- The destination number is reachable from the Vobiz trunk.
- The LiveKit room still has the SIP participant.
- The transfer target is in E.164 form.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| The model says transfers are unavailable | `ENABLE_TRANSFER=true` is set and the agent was restarted. |
| Status 500 or authentication retry | The Vobiz trunk credentials or transfer configuration are wrong. |
| Status 408 | The destination did not respond. Check the number and the Vobiz trunk. |
| The transfer starts but the destination does not ring | Check Vobiz call records and whether the trunk allows REFER to that route. |
| The agent disconnects but the caller hears nothing | The transfer may have left the agent successfully while the destination failed. Check the Vobiz side. |

Transfer failures return a spoken error to the caller.
They do not create a duplicate call.
