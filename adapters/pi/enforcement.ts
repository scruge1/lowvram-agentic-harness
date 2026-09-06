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
  pi.on("tool_execution_end", async (event) => {
    send({
      event_type: "tool_result",
      status: event.isError ? "failed" : "success",
      tool_name: event.toolName,
      tool_input: event.args,
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
