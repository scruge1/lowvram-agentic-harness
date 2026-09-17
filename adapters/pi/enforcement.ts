/** Translate Pi tool and completion events into the portable enforcement protocol. */

import { execFileSync } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Directive = { allow?: boolean; reason?: string };

function send(payload: object): Directive {
  const executable = process.env.TRUSTED_TASK_COMMAND ?? "trusted-task";
  const output = execFileSync(
    executable,
    ["hook", "--host", "normalized"],
    { input: JSON.stringify(payload), encoding: "utf8" },
  );
  return JSON.parse(output || "{}") as Directive;
}

export default function (pi: ExtensionAPI) {
  const pendingInputs = new Map<string, unknown>();

  pi.on("tool_execution_start", async (event) => {
    pendingInputs.set(event.toolCallId, event.args);
  });

  pi.on("tool_execution_end", async (event) => {
    const toolInput = pendingInputs.get(event.toolCallId) ?? {};
    pendingInputs.delete(event.toolCallId);
    send({
      event_type: "tool_result",
      tool_call_id: event.toolCallId,
      status: event.isError ? "failed" : "success",
      tool_name: event.toolName,
      tool_input: toolInput,
      error_summary: event.isError ? "Pi tool returned an error" : "",
    });
  });

  pi.on("agent_settled", async () => {
    const directive = send({ event_type: "completion_check" });
    if (directive.allow === false && directive.reason) {
      pi.sendMessage(
        {
          customType: "trusted-task-enforcement",
          content: directive.reason,
          display: true,
        },
        { triggerTurn: true, deliverAs: "followUp" },
      );
    }
  });
}
