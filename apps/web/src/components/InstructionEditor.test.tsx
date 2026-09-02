import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { InstructionDocument } from "../api/client";
import { InstructionEditor, type CapsuleSelection } from "./InstructionEditor";

const capsule = (nonce: number): CapsuleSelection => ({
  nonce,
  label: "来源一 · F-01",
  reference: {
    type: "capsule",
    task_version_id: "version-1",
    report_id: "report-1",
    item_id: "F-01",
  report_kind: "source" as const,
  },
});

describe("InstructionEditor", () => {
  it("inserts a non-editable capsule at the current cursor position", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn<(value: InstructionDocument) => void>();
    const view = render(
      <InstructionEditor taskId="task-1" value={{ content: [] }} onChange={onChange} />,
    );
    const editor = screen.getByRole("textbox", { name: "立言指令（可选）" });
    await user.type(editor, "挑战");
    view.rerender(
      <InstructionEditor
        taskId="task-1"
        value={onChange.mock.calls.at(-1)![0]}
        selection={capsule(1)}
        onChange={onChange}
      />,
    );
    await user.keyboard("并改写");

    expect(screen.getByText("来源一 · F-01")).toHaveAttribute("contenteditable", "false");
    expect(onChange.mock.calls.at(-1)![0]).toEqual({
      content: [
        { type: "text", text: "挑战" },
        {
          type: "capsule",
          task_version_id: "version-1",
          report_id: "report-1",
          item_id: "F-01",
  report_kind: "source" as const,
        },
        { type: "text", text: "并改写" },
      ],
    });
  });

  it("locates an existing capsule instead of duplicating it", () => {
    const onChange = vi.fn<(value: InstructionDocument) => void>();
    const view = render(
      <InstructionEditor
        taskId="task-1"
        value={{ content: [] }}
        selection={capsule(1)}
        onChange={onChange}
      />,
    );
    view.rerender(
      <InstructionEditor
        taskId="task-1"
        value={onChange.mock.calls.at(-1)![0]}
        selection={capsule(2)}
        onChange={onChange}
      />,
    );

    expect(screen.getAllByText("来源一 · F-01")).toHaveLength(1);
    expect(screen.getByText("来源一 · F-01")).toHaveClass("ProseMirror-selectednode");
  });

  it("does not confuse the same report item across task versions", () => {
    const onChange = vi.fn<(value: InstructionDocument) => void>();
    const view = render(
      <InstructionEditor
        taskId="task-1"
        value={{ content: [] }}
        selection={capsule(1)}
        onChange={onChange}
      />,
    );
    view.rerender(
      <InstructionEditor
        taskId="task-1"
        value={onChange.mock.calls.at(-1)![0]}
        selection={{
          ...capsule(2),
          reference: { ...capsule(2).reference, task_version_id: "version-2" },
        }}
        onChange={onChange}
      />,
    );

    expect(screen.getAllByText("来源一 · F-01")).toHaveLength(2);
  });

  it("deletes a selected capsule as one atomic item", async () => {
    const onChange = vi.fn<(value: InstructionDocument) => void>();
    const view = render(
      <InstructionEditor
        taskId="task-1"
        value={{ content: [] }}
        selection={capsule(1)}
        onChange={onChange}
      />,
    );

    view.rerender(
      <InstructionEditor
        taskId="task-1"
        value={onChange.mock.calls.at(-1)![0]}
        selection={capsule(2)}
        onChange={onChange}
      />,
    );
    const editor = screen.getByRole("textbox", { name: "立言指令（可选）" });
    fireEvent.keyDown(editor, { key: "Backspace" });

    expect(screen.queryByText("来源一 · F-01")).not.toBeInTheDocument();
    expect(onChange.mock.calls.at(-1)![0]).toEqual({ content: [] });
  });
});
